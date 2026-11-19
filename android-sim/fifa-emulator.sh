#!/usr/bin/env bash
# Launch the fifa_pixel AVD on the NVIDIA GPU (Intel+NVIDIA hybrid needs GL and Vulkan on one GPU).
# Everything (SDK, AVD, .android state) lives under this directory.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ANDROID_HOME="$HERE/Android/Sdk" ANDROID_SDK_ROOT="$HERE/Android/Sdk"
export ANDROID_USER_HOME="$HERE/Android/.android" ANDROID_EMULATOR_HOME="$HERE/Android/.android" ANDROID_AVD_HOME="$HERE/Android/.android/avd"
export __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only
export QT_IM_MODULE=
exec "$ANDROID_HOME/emulator/emulator" -avd "${1:-fifa_pixel}" -gpu host -no-metrics "${@:2}"
