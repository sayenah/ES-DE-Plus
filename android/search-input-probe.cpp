//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  search-input-probe.cpp
//
//  Written for ES-DE-Plus. Debug-only real SDL virtual-controller input for CI.
//  No production bridge API or frontend behavior is replaced.
//

#if defined(__ANDROID__) && !defined(NDEBUG)
#include <SDL2/SDL.h>
#include <jni.h>
#include <string>

extern "C" JNIEXPORT jboolean JNICALL
Java_org_esdeplus_frontend_TouchSmoke_00024SearchInput_nativeButton(JNIEnv*, jobject, jint button)
{
    static SDL_JoystickID controller {-1};
    if (button == -1) {
        if (controller >= 0)
            return JNI_TRUE;
        const int index = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, 6, 15, 0);
        if (index < 0)
            return JNI_FALSE;
        char guid[33];
        SDL_JoystickGetGUIDString(SDL_JoystickGetDeviceGUID(index), guid, sizeof(guid));
        const std::string mapping =
            std::string(guid) +
            ",Search smoke "
            "controller,a:b0,b:b1,x:b2,y:b3,back:b4,guide:b5,start:b6,leftstick:b7,rightstick:b8,"
            "leftshoulder:b9,rightshoulder:b10,dpup:b11,dpdown:b12,dpleft:b13,dpright:b14,leftx:a0,"
            "lefty:a1,rightx:a2,righty:a3,lefttrigger:a4,righttrigger:a5,";
        if (SDL_GameControllerAddMapping(mapping.c_str()) < 0)
            return JNI_FALSE;
        controller = SDL_JoystickGetDeviceInstanceID(index);
        return JNI_TRUE;
    }
    if (controller < 0 || button < 0 || button >= SDL_CONTROLLER_BUTTON_MAX)
        return JNI_FALSE;
    SDL_Event event {};
    event.type = SDL_CONTROLLERBUTTONDOWN;
    event.cbutton.which = controller;
    event.cbutton.button = static_cast<Uint8>(button);
    event.cbutton.state = SDL_PRESSED;
    if (SDL_PushEvent(&event) != 1)
        return JNI_FALSE;
    event.type = SDL_CONTROLLERBUTTONUP;
    event.cbutton.state = SDL_RELEASED;
    return SDL_PushEvent(&event) == 1 ? JNI_TRUE : JNI_FALSE;
}
#endif
