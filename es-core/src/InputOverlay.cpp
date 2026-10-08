// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus; the deferred overlay emits no synthetic input.
#include "InputOverlay.h"
#if defined(__ANDROID__)
InputOverlay& InputOverlay::getInstance()
{
    static InputOverlay instance;
    return instance;
}
#endif
