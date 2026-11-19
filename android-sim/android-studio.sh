#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ANDROID_HOME="$HERE/Android/Sdk" ANDROID_SDK_ROOT="$HERE/Android/Sdk"
export ANDROID_USER_HOME="$HERE/Android/.android" ANDROID_EMULATOR_HOME="$HERE/Android/.android" ANDROID_AVD_HOME="$HERE/Android/.android/avd"
export __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only
exec "$HERE/android-studio/bin/studio.sh" "$@"
