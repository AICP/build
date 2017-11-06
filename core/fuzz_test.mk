###########################################
## A thin wrapper around BUILD_EXECUTABLE
## Common flags for fuzz tests are added.
###########################################
$(call record-module-type,FUZZ_TEST)

ifdef LOCAL_SDK_VERSION
    $(error $(LOCAL_PATH): $(LOCAL_MODULE): NDK fuzz tests are not supported.)
endif

LOCAL_CFLAGS += -fsanitize-coverage=trace-pc-guard
LOCAL_STATIC_LIBRARIES += libFuzzer

ifdef LOCAL_MODULE_PATH
$(error $(LOCAL_PATH): Do not set LOCAL_MODULE_PATH when building test $(LOCAL_MODULE))
endif

ifdef LOCAL_MODULE_PATH_32
$(error $(LOCAL_PATH): Do not set LOCAL_MODULE_PATH_32 when building test $(LOCAL_MODULE))
endif

ifdef LOCAL_MODULE_PATH_64
$(error $(LOCAL_PATH): Do not set LOCAL_MODULE_PATH_64 when building test $(LOCAL_MODULE))
endif

LOCAL_MODULE_PATH_64 := $(TARGET_OUT_DATA_NATIVE_TESTS)/fuzzers/$(LOCAL_MODULE)
LOCAL_MODULE_PATH_32 := $($(TARGET_2ND_ARCH_VAR_PREFIX)TARGET_OUT_DATA_NATIVE_TESTS)/fuzzers/$(LOCAL_MODULE)

ifndef LOCAL_MULTILIB
ifndef LOCAL_32_BIT_ONLY
LOCAL_MULTILIB := both
endif
endif

include $(BUILD_EXECUTABLE)
