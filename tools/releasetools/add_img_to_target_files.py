#!/usr/bin/env python
#
# Copyright (C) 2014 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Given a target-files zipfile that does not contain images (ie, does
not have an IMAGES/ top-level subdirectory), produce the images and
add them to the zipfile.

Usage:  add_img_to_target_files [flag] target_files

  -a  (--add_missing)
      Build and add missing images to "IMAGES/". If this option is
      not specified, this script will simply exit when "IMAGES/"
      directory exists in the target file.

  -r  (--rebuild_recovery)
      Rebuild the recovery patch and write it to the system image. Only
      meaningful when system image needs to be rebuilt.

  --replace_verity_private_key
      Replace the private key used for verity signing. (same as the option
      in sign_target_files_apks)

  --replace_verity_public_key
       Replace the certificate (public key) used for verity verification. (same
       as the option in sign_target_files_apks)

  --is_signing
      Skip building & adding the images for "userdata" and "cache" if we
      are signing the target files.
"""

from __future__ import print_function

import sys

if sys.hexversion < 0x02070000:
  print("Python 2.7 or newer is required.", file=sys.stderr)
  sys.exit(1)

import datetime
import errno
import os
import shlex
import shutil
import subprocess
import tempfile
import zipfile

import build_image
import common
import rangelib
import sparse_img

OPTIONS = common.OPTIONS

OPTIONS.add_missing = False
OPTIONS.rebuild_recovery = False
OPTIONS.replace_verity_public_key = False
OPTIONS.replace_verity_private_key = False
OPTIONS.is_signing = False


class OutputFile(object):
  def __init__(self, output_zip, input_dir, prefix, name):
    self._output_zip = output_zip
    self.input_name = os.path.join(input_dir, prefix, name)

    if self._output_zip:
      self._zip_name = os.path.join(prefix, name)

      root, suffix = os.path.splitext(name)
      self.name = common.MakeTempFile(prefix=root + '-', suffix=suffix)
    else:
      self.name = self.input_name

  def Write(self):
    if self._output_zip:
      common.ZipWrite(self._output_zip, self.name, self._zip_name)


def GetCareMap(which, imgname):
  """Generate care_map of system (or vendor) partition"""

  assert which in ("system", "vendor")

  simg = sparse_img.SparseImage(imgname)
  care_map_list = []
  care_map_list.append(which)

  care_map_ranges = simg.care_map
  key = which + "_adjusted_partition_size"
  adjusted_blocks = OPTIONS.info_dict.get(key)
  if adjusted_blocks:
    assert adjusted_blocks > 0, "blocks should be positive for " + which
    care_map_ranges = care_map_ranges.intersect(rangelib.RangeSet(
        "0-%d" % (adjusted_blocks,)))

  care_map_list.append(care_map_ranges.to_string_raw())
  return care_map_list


def AddSystem(output_zip, prefix="IMAGES/", recovery_img=None, boot_img=None):
  """Turn the contents of SYSTEM into a system image and store it in
  output_zip. Returns the name of the system image file."""

  img = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "system.img")
  if os.path.exists(img.input_name):
    print("system.img already exists in %s, no need to rebuild..." % (prefix,))
    return img.input_name

  def output_sink(fn, data):
    ofile = open(os.path.join(OPTIONS.input_tmp, "SYSTEM", fn), "w")
    ofile.write(data)
    ofile.close()

  if OPTIONS.rebuild_recovery:
    print("Building new recovery patch")
    common.MakeRecoveryPatch(OPTIONS.input_tmp, output_sink, recovery_img,
                             boot_img, info_dict=OPTIONS.info_dict)

  block_list = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "system.map")
  CreateImage(OPTIONS.input_tmp, OPTIONS.info_dict, "system", img,
              block_list=block_list)

  return img.name


def AddSystemOther(output_zip, prefix="IMAGES/"):
  """Turn the contents of SYSTEM_OTHER into a system_other image
  and store it in output_zip."""

  img = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "system_other.img")
  if os.path.exists(img.input_name):
    print("system_other.img already exists in %s, no need to rebuild..." % (
        prefix,))
    return

  CreateImage(OPTIONS.input_tmp, OPTIONS.info_dict, "system_other", img)


def AddVendor(output_zip, prefix="IMAGES/"):
  """Turn the contents of VENDOR into a vendor image and store in it
  output_zip."""

  img = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "vendor.img")
  if os.path.exists(img.input_name):
    print("vendor.img already exists in %s, no need to rebuild..." % (prefix,))
    return img.input_name

  block_list = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "vendor.map")
  CreateImage(OPTIONS.input_tmp, OPTIONS.info_dict, "vendor", img,
              block_list=block_list)
  return img.name


def CreateImage(input_dir, info_dict, what, output_file, block_list=None):
  print("creating " + what + ".img...")

  # The name of the directory it is making an image out of matters to
  # mkyaffs2image.  It wants "system" but we have a directory named
  # "SYSTEM", so create a symlink.
  temp_dir = tempfile.mkdtemp()
  OPTIONS.tempfiles.append(temp_dir)
  try:
    os.symlink(os.path.join(input_dir, what.upper()),
               os.path.join(temp_dir, what))
  except OSError as e:
    # bogus error on my mac version?
    #   File "./build/tools/releasetools/img_from_target_files"
    #     os.path.join(OPTIONS.input_tmp, "system"))
    # OSError: [Errno 17] File exists
    if e.errno == errno.EEXIST:
      pass

  image_props = build_image.ImagePropFromGlobalDict(info_dict, what)
  fstab = info_dict["fstab"]
  mount_point = "/" + what
  if fstab and mount_point in fstab:
    image_props["fs_type"] = fstab[mount_point].fs_type

  # Use a fixed timestamp (01/01/2009) when packaging the image.
  # Bug: 24377993
  epoch = datetime.datetime.fromtimestamp(0)
  timestamp = (datetime.datetime(2009, 1, 1) - epoch).total_seconds()
  image_props["timestamp"] = int(timestamp)

  if what == "system":
    fs_config_prefix = ""
  else:
    fs_config_prefix = what + "_"

  fs_config = os.path.join(
      input_dir, "META/" + fs_config_prefix + "filesystem_config.txt")
  if not os.path.exists(fs_config):
    fs_config = None

  # Override values loaded from info_dict.
  if fs_config:
    image_props["fs_config"] = fs_config
  if block_list:
    image_props["block_list"] = block_list.name

  succ = build_image.BuildImage(os.path.join(temp_dir, what),
                                image_props, output_file.name)
  assert succ, "build " + what + ".img image failed"

  output_file.Write()
  if block_list:
    block_list.Write()

  is_verity_partition = "verity_block_device" in image_props
  verity_supported = image_props.get("verity") == "true"
  if is_verity_partition and verity_supported:
    adjusted_blocks_value = image_props.get("partition_size")
    if adjusted_blocks_value:
      adjusted_blocks_key = what + "_adjusted_partition_size"
      info_dict[adjusted_blocks_key] = int(adjusted_blocks_value)/4096 - 1


def AddUserdata(output_zip, prefix="IMAGES/"):
  """Create a userdata image and store it in output_zip.

  In most case we just create and store an empty userdata.img;
  But the invoker can also request to create userdata.img with real
  data from the target files, by setting "userdata_img_with_data=true"
  in OPTIONS.info_dict.
  """

  img = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "userdata.img")
  if os.path.exists(img.input_name):
    print("userdata.img already exists in %s, no need to rebuild..." % (
        prefix,))
    return

  # Skip userdata.img if no size.
  image_props = build_image.ImagePropFromGlobalDict(OPTIONS.info_dict, "data")
  if not image_props.get("partition_size"):
    return

  print("creating userdata.img...")

  # Use a fixed timestamp (01/01/2009) when packaging the image.
  # Bug: 24377993
  epoch = datetime.datetime.fromtimestamp(0)
  timestamp = (datetime.datetime(2009, 1, 1) - epoch).total_seconds()
  image_props["timestamp"] = int(timestamp)

  # The name of the directory it is making an image out of matters to
  # mkyaffs2image.  So we create a temp dir, and within it we create an
  # empty dir named "data", or a symlink to the DATA dir,
  # and build the image from that.
  temp_dir = tempfile.mkdtemp()
  OPTIONS.tempfiles.append(temp_dir)
  user_dir = os.path.join(temp_dir, "data")
  empty = (OPTIONS.info_dict.get("userdata_img_with_data") != "true")
  if empty:
    # Create an empty dir.
    os.mkdir(user_dir)
  else:
    # Symlink to the DATA dir.
    os.symlink(os.path.join(OPTIONS.input_tmp, "DATA"),
               user_dir)

  fstab = OPTIONS.info_dict["fstab"]
  if fstab:
    image_props["fs_type"] = fstab["/data"].fs_type
  succ = build_image.BuildImage(user_dir, image_props, img.name)
  assert succ, "build userdata.img image failed"

  common.CheckSize(img.name, "userdata.img", OPTIONS.info_dict)
  img.Write()


def AddVBMeta(output_zip, boot_img_path, system_img_path, vendor_img_path,
              prefix="IMAGES/"):
  """Create a VBMeta image and store it in output_zip."""
  img = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "vbmeta.img")
  avbtool = os.getenv('AVBTOOL') or "avbtool"
  cmd = [avbtool, "make_vbmeta_image",
         "--output", img.name,
         "--include_descriptors_from_image", boot_img_path,
         "--include_descriptors_from_image", system_img_path]
  if vendor_img_path is not None:
    cmd.extend(["--include_descriptors_from_image", vendor_img_path])
  if OPTIONS.info_dict.get("system_root_image", None) == "true":
    cmd.extend(["--setup_rootfs_from_kernel", system_img_path])
  common.AppendAVBSigningArgs(cmd)
  args = OPTIONS.info_dict.get("board_avb_make_vbmeta_image_args", None)
  if args and args.strip():
    cmd.extend(shlex.split(args))
  p = common.Run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  p.communicate()
  assert p.returncode == 0, "avbtool make_vbmeta_image failed"
  img.Write()


def AddPartitionTable(output_zip, prefix="IMAGES/"):
  """Create a partition table image and store it in output_zip."""

  img = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "partition-table.img")
  bpt = OutputFile(output_zip, OPTIONS.input_tmp, prefix, "partition-table.bpt")

  # use BPTTOOL from environ, or "bpttool" if empty or not set.
  bpttool = os.getenv("BPTTOOL") or "bpttool"
  cmd = [bpttool, "make_table", "--output_json", bpt.name,
         "--output_gpt", img.name]
  input_files_str = OPTIONS.info_dict["board_bpt_input_files"]
  input_files = input_files_str.split(" ")
  for i in input_files:
    cmd.extend(["--input", i])
  disk_size = OPTIONS.info_dict.get("board_bpt_disk_size")
  if disk_size:
    cmd.extend(["--disk_size", disk_size])
  args = OPTIONS.info_dict.get("board_bpt_make_table_args")
  if args:
    cmd.extend(shlex.split(args))

  p = common.Run(cmd, stdout=subprocess.PIPE)
  p.communicate()
  assert p.returncode == 0, "bpttool make_table failed"

  img.Write()
  bpt.Write()

def AddImagesToTargetFiles(filename):
  if os.path.isdir(filename):
    OPTIONS.input_tmp = os.path.abspath(filename)
    input_zip = None
  else:
    OPTIONS.input_tmp, input_zip = common.UnzipTemp(filename)

  if not OPTIONS.add_missing:
    if os.path.isdir(os.path.join(OPTIONS.input_tmp, "IMAGES")):
      print("target_files appears to already contain images.")
      sys.exit(1)

  has_vendor = os.path.isdir(os.path.join(OPTIONS.input_tmp, "VENDOR"))
  has_system_other = os.path.isdir(os.path.join(OPTIONS.input_tmp,
                                                "SYSTEM_OTHER"))

  if input_zip:
    OPTIONS.info_dict = common.LoadInfoDict(input_zip, OPTIONS.input_tmp)

    common.ZipClose(input_zip)
    output_zip = zipfile.ZipFile(filename, "a",
                                 compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=True)
  else:
    OPTIONS.info_dict = common.LoadInfoDict(filename, filename)
    output_zip = None
    images_dir = os.path.join(OPTIONS.input_tmp, "IMAGES")
    if not os.path.isdir(images_dir):
      os.makedirs(images_dir)
    images_dir = None

  has_recovery = (OPTIONS.info_dict.get("no_recovery") != "true")

  def banner(s):
    print("\n\n++++ " + s + " ++++\n\n")

  prebuilt_path = os.path.join(OPTIONS.input_tmp, "IMAGES", "boot.img")
  boot_image = None
  if os.path.exists(prebuilt_path):
    banner("boot")
    print("boot.img already exists in IMAGES/, no need to rebuild...")
    if OPTIONS.rebuild_recovery:
      boot_image = common.GetBootableImage(
          "IMAGES/boot.img", "boot.img", OPTIONS.input_tmp, "BOOT")
  else:
    banner("boot")
    boot_image = common.GetBootableImage(
        "IMAGES/boot.img", "boot.img", OPTIONS.input_tmp, "BOOT")
    if boot_image:
      if output_zip:
        boot_image.AddToZip(output_zip)
      else:
        boot_image.WriteToDir(OPTIONS.input_tmp)

  recovery_image = None
  if has_recovery:
    banner("recovery")
    prebuilt_path = os.path.join(OPTIONS.input_tmp, "IMAGES", "recovery.img")
    if os.path.exists(prebuilt_path):
      print("recovery.img already exists in IMAGES/, no need to rebuild...")
      if OPTIONS.rebuild_recovery:
        recovery_image = common.GetBootableImage(
            "IMAGES/recovery.img", "recovery.img", OPTIONS.input_tmp,
            "RECOVERY")
    else:
      recovery_image = common.GetBootableImage(
          "IMAGES/recovery.img", "recovery.img", OPTIONS.input_tmp, "RECOVERY")
      if recovery_image:
        if output_zip:
          recovery_image.AddToZip(output_zip)
        else:
          recovery_image.WriteToDir(OPTIONS.input_tmp)

      banner("recovery (two-step image)")
      # The special recovery.img for two-step package use.
      recovery_two_step_image = common.GetBootableImage(
          "IMAGES/recovery-two-step.img", "recovery-two-step.img",
          OPTIONS.input_tmp, "RECOVERY", two_step_image=True)
      if recovery_two_step_image:
        if output_zip:
          recovery_two_step_image.AddToZip(output_zip)
        else:
          recovery_two_step_image.WriteToDir(OPTIONS.input_tmp)

  banner("system")
  system_img_path = AddSystem(
    output_zip, recovery_img=recovery_image, boot_img=boot_image)
  vendor_img_path = None
  if has_vendor:
    banner("vendor")
    vendor_img_path = AddVendor(output_zip)
  if has_system_other:
    banner("system_other")
    AddSystemOther(output_zip)
  if not OPTIONS.is_signing:
    banner("userdata")
    AddUserdata(output_zip)
  if OPTIONS.info_dict.get("board_bpt_enable", None) == "true":
    banner("partition-table")
    AddPartitionTable(output_zip)
  if OPTIONS.info_dict.get("board_avb_enable", None) == "true":
    banner("vbmeta")
    boot_contents = boot_image.WriteToTemp()
    AddVBMeta(output_zip, boot_contents.name, system_img_path, vendor_img_path)

  # For devices using A/B update, copy over images from RADIO/ and/or
  # VENDOR_IMAGES/ to IMAGES/ and make sure we have all the needed
  # images ready under IMAGES/. All images should have '.img' as extension.
  banner("radio")
  ab_partitions = os.path.join(OPTIONS.input_tmp, "META", "ab_partitions.txt")
  if os.path.exists(ab_partitions):
    with open(ab_partitions, 'r') as f:
      lines = f.readlines()
    # For devices using A/B update, generate care_map for system and vendor
    # partitions (if present), then write this file to target_files package.
    care_map_list = []
    for line in lines:
      if line.strip() == "system" and OPTIONS.info_dict.get(
          "system_verity_block_device", None) is not None:
        assert os.path.exists(system_img_path)
        care_map_list += GetCareMap("system", system_img_path)
      if line.strip() == "vendor" and OPTIONS.info_dict.get(
          "vendor_verity_block_device", None) is not None:
        assert os.path.exists(vendor_img_path)
        care_map_list += GetCareMap("vendor", vendor_img_path)

      img_name = line.strip() + ".img"
      prebuilt_path = os.path.join(OPTIONS.input_tmp, "IMAGES", img_name)
      if os.path.exists(prebuilt_path):
        print("%s already exists, no need to overwrite..." % (img_name,))
        continue

      img_radio_path = os.path.join(OPTIONS.input_tmp, "RADIO", img_name)
      img_vendor_dir = os.path.join(
        OPTIONS.input_tmp, "VENDOR_IMAGES")
      if os.path.exists(img_radio_path):
        if output_zip:
          common.ZipWrite(output_zip, img_radio_path,
                          os.path.join("IMAGES", img_name))
        else:
          shutil.copy(img_radio_path, prebuilt_path)
      else:
        for root, _, files in os.walk(img_vendor_dir):
          if img_name in files:
            if output_zip:
              common.ZipWrite(output_zip, os.path.join(root, img_name),
                os.path.join("IMAGES", img_name))
            else:
              shutil.copy(os.path.join(root, img_name), prebuilt_path)
            break

      if output_zip:
        # Zip spec says: All slashes MUST be forward slashes.
        img_path = 'IMAGES/' + img_name
        assert img_path in output_zip.namelist(), "cannot find " + img_name
      else:
        img_path = os.path.join(OPTIONS.input_tmp, "IMAGES", img_name)
        assert os.path.exists(img_path), "cannot find " + img_name

    if care_map_list:
      file_path = "META/care_map.txt"
      if output_zip:
        common.ZipWriteStr(output_zip, file_path, '\n'.join(care_map_list))
      else:
        with open(os.path.join(OPTIONS.input_tmp, file_path), 'w') as fp:
          fp.write('\n'.join(care_map_list))

  if output_zip:
    common.ZipClose(output_zip)

def main(argv):
  def option_handler(o, a):
    if o in ("-a", "--add_missing"):
      OPTIONS.add_missing = True
    elif o in ("-r", "--rebuild_recovery",):
      OPTIONS.rebuild_recovery = True
    elif o == "--replace_verity_private_key":
      OPTIONS.replace_verity_private_key = (True, a)
    elif o == "--replace_verity_public_key":
      OPTIONS.replace_verity_public_key = (True, a)
    elif o == "--is_signing":
      OPTIONS.is_signing = True
    else:
      return False
    return True

  args = common.ParseOptions(
      argv, __doc__, extra_opts="ar",
      extra_long_opts=["add_missing", "rebuild_recovery",
                       "replace_verity_public_key=",
                       "replace_verity_private_key=",
                       "is_signing"],
      extra_option_handler=option_handler)


  if len(args) != 1:
    common.Usage(__doc__)
    sys.exit(1)

  AddImagesToTargetFiles(args[0])
  print("done.")

if __name__ == '__main__':
  try:
    common.CloseInheritedPipes()
    main(sys.argv[1:])
  except common.ExternalError as e:
    print("\n   ERROR: %s\n" % (e,))
    sys.exit(1)
  finally:
    common.Cleanup()
