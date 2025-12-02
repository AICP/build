# Copyright (C) 2023 The Android Open Source Project
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


# -----------------------------------------------------------------
# Determine which pass this is.
# -----------------------------------------------------------------
# On the first pass, we are asked for only PRODUCT_RELEASE_CONFIG_MAPS,
# on the second pass, we are asked for whatever else is wanted.
_final_product_config_pass:=
ifneq (PRODUCT_RELEASE_CONFIG_MAPS,$(DUMP_MANY_VARS))
    _final_product_config_pass:=true
endif

# -----------------------------------------------------------------
# Choose the flag files
# -----------------------------------------------------------------
# Release configs are defined in reflease_config_map files, which map
# the short name (e.g. -next) used in lunch to the starlark files
# defining the build flag values.
#
# (If you're thinking about aconfig flags, there is one build flag,
# RELEASE_ACONFIG_VALUE_SETS, that sets which aconfig_value_set
# module to use to set the aconfig flag values.)
#
# The short release config names *can* appear multiple times, to allow
# for AOSP and vendor specific flags under the same name, but the
# individual flag values must appear in exactly one config.  Vendor
# does not override AOSP, or anything like that.  This is because
# vendor code usually includes prebuilts, and having vendor compile
# with different flags from AOSP increases the likelihood of flag
# mismatch.

# Do this first, because we're going to unset TARGET_RELEASE before
# including anyone, so they don't start making conditionals based on it.
# This logic is in make because starlark doesn't understand optional
# vendor files.

# If this is a google source tree, restrict it to only the one file
# which has OWNERS control.  If it isn't let others define their own.
_protobuf_map_files := build/release/release_config_map.textproto \
    $(wildcard vendor/google_shared/build/release/release_config_map.textproto) \
    $(if $(wildcard vendor/google/release/release_config_map.textproto), \
        vendor/google/release/release_config_map.textproto, \
        $(sort \
            $(wildcard device/*/release/release_config_map.textproto) \
            $(wildcard device/*/*/release/release_config_map.textproto) \
            $(wildcard vendor/*/release/release_config_map.textproto) \
            $(wildcard vendor/*/*/release/release_config_map.textproto) \
        ) \
    )

# PRODUCT_RELEASE_CONFIG_MAPS is set by Soong using an initial run of product
# config to capture only the list of config maps needed by the build.
# Keep them in the order provided, but remove duplicates.
# Treat any .mk file as an error, since those have not worked since ap3a.
$(foreach map,$(PRODUCT_RELEASE_CONFIG_MAPS), \
    $(if $(filter $(basename $(map)).mk,$(map)),\
        $(error $(map): use of release_config_map.mk files is not supported))\
    $(if $(filter $(basename $(map)),$(basename $(_protobuf_map_files))),, \
        $(eval _protobuf_map_files += $(map))) \
)

# The .textproto files are the canonical source of truth.
_args := --guard=false $(foreach map,$(_protobuf_map_files), --map $(map) )
_args += --allow-missing=true
ifneq (,$(TARGET_PRODUCT))
    _args += --product $(TARGET_PRODUCT)
endif
_flags_dir:=$(OUT_DIR)/soong/release-config
_flags_file:=$(_flags_dir)/release_config-$(TARGET_PRODUCT)-$(TARGET_RELEASE).vars
# release-config generates $(_flags_varmk)
_flags_varmk:=$(_flags_file:.vars=.varmk)
$(shell $(OUT_DIR)/release-config $(_args) >$(OUT_DIR)/release-config.${TARGET_PRODUCT}.out && touch -t 200001010000 $(_flags_varmk))
$(if $(filter-out 0,$(.SHELLSTATUS)),$(error release-config failed to run))
ifneq (,$(_final_product_config_pass))
    # Save the final version of the config.
    $(shell if ! cmp --quiet $(_flags_varmk) $(_flags_file); then cp $(_flags_varmk) $(_flags_file); fi)
    # This will also set ALL_RELEASE_CONFIGS_FOR_PRODUCT and _used_files for us.
    $(eval include $(_flags_file))
    $(KATI_extra_file_deps $(OUT_DIR)/release-config $(_protobuf_map_files) $(_flags_file))
    ifneq (,$(_disallow_lunch_use))
        $(error Release config ${TARGET_RELEASE} is disallowed for build.  Please use one of: $(ALL_RELEASE_CONFIGS_FOR_PRODUCT))
    endif
else
    # This is the first pass of product config.
    $(eval include $(_flags_varmk))
endif
_args:=
_used_files:=
_flags_dir:=
_flags_file:=
_flags_varmk:=

ifeq ($(TARGET_RELEASE),)
    # We allow some internal paths to explicitly set TARGET_RELEASE to the
    # empty string.  For the most part, 'make' treats unset and empty string as
    # the same.  But the following line differentiates, and will only assign
    # if the variable was completely unset.
    TARGET_RELEASE ?= was_unset
    ifeq ($(TARGET_RELEASE),was_unset)
        $(error No release config set for target; please set TARGET_RELEASE, or if building on the command line use 'lunch <target>-<release>-<build_type>', where release is one of: $(ALL_RELEASE_CONFIGS_FOR_PRODUCT))
    endif
    # Instead of leaving this string empty, we want to default to a valid
    # setting.  Full builds coming through this path is a bug, but in case
    # of such a bug, we want to at least get consistent, valid results.
    TARGET_RELEASE = trunk_staging
endif

# During pass 1 of product config, using a non-existent release config is not an error.
# We can safely assume that we are doing pass 1 if DUMP_MANY_VARS=="PRODUCT_RELEASE_CONFIG_MAPS".
ifneq (,$(_final_product_config_pass))
    ifeq ($(filter $(ALL_RELEASE_CONFIGS_FOR_PRODUCT), $(TARGET_RELEASE)),)
        $(error No release config found for TARGET_RELEASE: $(TARGET_RELEASE). Available releases are: $(ALL_RELEASE_CONFIGS_FOR_PRODUCT))
    endif
endif

# TODO: Remove this check after enough people have sourced lunch that we don't
# need to worry about it trying to do get_build_vars TARGET_RELEASE. Maybe after ~9/2023
ifneq ($(CALLED_FROM_SETUP),true)
define TARGET_RELEASE
$(error TARGET_RELEASE may not be accessed directly. Use individual flags.)
endef
else
TARGET_RELEASE:=
endif
.KATI_READONLY := TARGET_RELEASE

_protobuf_map_files:=
