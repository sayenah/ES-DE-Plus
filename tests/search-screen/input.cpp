//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  input.cpp
//
//  Written for ES-DE-Plus. Test-only SDL event injection and actual GL framebuffer capture.
//  Interposes SDL boundaries, never substitutes search, rendering or game-list logic.
//

#include <SDL2/SDL.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <fstream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace
{
    template <typename Function> Function real(const char* name)
    {
        auto symbol = dlsym(RTLD_NEXT, name);
        if (!symbol)
            std::abort();
        return reinterpret_cast<Function>(symbol);
    }
    std::string directory()
    {
        const auto value = std::getenv("ESDE_SEARCH_PROBE");
        return value ? value : "";
    }
    unsigned sequence {0};
    std::string capture;
    SDL_JoystickID controller {-1};
    SDL_Event queued {};
    SDL_Event release {};
    bool typeWhileOpening {false};
    std::vector<double> gpuWaits;
    void acknowledge()
    {
        std::ofstream(directory() + "/ack.new") << sequence << '\n';
        std::rename((directory() + "/ack.new").c_str(), (directory() + "/ack").c_str());
    }
} // namespace

extern "C" void SDLCALL SDL_SetTextInputRect(const SDL_Rect* rect)
{
    static const auto forward = real<decltype(&SDL_SetTextInputRect)>("SDL_SetTextInputRect");
    forward(rect);
    if (typeWhileOpening && rect && rect->w > 0 && rect->h > 0) {
        typeWhileOpening = false;
        // Like Android's nativeCommitText, text arriving on the platform thread is
        // discarded when SDL text events are disabled. Inject while the native field
        // is being positioned, before the constructor returns to the event loop.
        const bool active = SDL_IsTextInputActive();
        std::ofstream(directory() + "/opening-text-state") << active << '\n';
        if (active) {
            SDL_Event text {};
            text.type = SDL_TEXTINPUT;
            SDL_strlcpy(text.text.text, "f", sizeof(text.text.text));
            SDL_PushEvent(&text);
        }
    }
}

extern "C" int SDLCALL SDL_InitSubSystem(Uint32 flags)
{
    static const auto forward = real<decltype(&SDL_InitSubSystem)>("SDL_InitSubSystem");
    const int result = forward(flags);
    if (!result && controller < 0 && SDL_WasInit(SDL_INIT_JOYSTICK)) {
        const int index = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, 6, 15, 0);
        if (index >= 0) {
            char guid[33];
            SDL_JoystickGetGUIDString(SDL_JoystickGetDeviceGUID(index), guid, sizeof(guid));
            const std::string mapping =
                std::string(guid) +
                ",Search smoke "
                "controller,a:b0,b:b1,x:b2,y:b3,back:b4,guide:b5,start:b6,leftstick:b7,rightstick:"
                "b8,leftshoulder:b9,rightshoulder:b10,dpup:b11,dpdown:b12,dpleft:b13,dpright:b14,"
                "leftx:a0,lefty:a1,rightx:a2,righty:a3,lefttrigger:a4,righttrigger:a5,";
            SDL_GameControllerAddMapping(mapping.c_str());
            controller = SDL_JoystickGetDeviceInstanceID(index);
        }
    }
    return result;
}

extern "C" void SDLCALL SDL_GL_SwapWindow(SDL_Window* window)
{
    static const auto forward = real<decltype(&SDL_GL_SwapWindow)>("SDL_GL_SwapWindow");
    if (std::getenv("ESDE_SEARCH_SYNC_GPU")) {
        // Separate diagnostic control. The ordinary capture journey stays unfenced.
        using Finish = void (*)();
        static const auto finish = reinterpret_cast<Finish>(SDL_GL_GetProcAddress("glFinish"));
        if (!finish)
            std::abort();
        const auto start = std::chrono::steady_clock::now();
        finish();
        gpuWaits.emplace_back(
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start)
                .count());
    }
    if (!capture.empty()) {
        int width {0}, height {0};
        SDL_GL_GetDrawableSize(window, &width, &height);
        using ReadPixels = void (*)(int, int, int, int, unsigned, unsigned, void*);
        const auto read = reinterpret_cast<ReadPixels>(SDL_GL_GetProcAddress("glReadPixels"));
        std::vector<unsigned char> pixels(static_cast<size_t>(width) * height * 4);
        read(0, 0, width, height, 0x1908 /* GL_RGBA */, 0x1401 /* GL_UNSIGNED_BYTE */,
             pixels.data());
        std::ofstream image(directory() + "/" + capture + ".ppm", std::ios::binary);
        image << "P6\n" << width << " " << height << "\n255\n";
        for (int y = height - 1; y >= 0; --y)
            for (int x {0}; x < width; ++x)
                image.write(reinterpret_cast<char*>(pixels.data() + (y * width + x) * 4), 3);
        image.close();
        capture.clear();
        acknowledge();
    }
    forward(window);
}

extern "C" int SDLCALL SDL_PollEvent(SDL_Event* event)
{
    static const auto forward = real<decltype(&SDL_PollEvent)>("SDL_PollEvent");
    if (!event || directory().empty())
        return forward(event);
    if (queued.type) {
        *event = queued;
        queued.type = 0;
        return 1;
    }
    if (release.type) {
        *event = release;
        release.type = 0;
        return 1;
    }
    unsigned incoming {0};
    std::string action;
    std::ifstream input(directory() + "/command");
    input >> incoming >> action;
    if (incoming <= sequence)
        return forward(event);
    sequence = incoming;
    std::string value;
    std::getline(input, value);
    if (!value.empty() && value.front() == ' ')
        value.erase(0, 1);
    SDL_zero(*event);
    if (action == "capture") {
        capture = value;
        return 0;
    }
    if (action == "quit") {
        if (!gpuWaits.empty()) {
            std::sort(gpuWaits.begin(), gpuWaits.end());
            std::fprintf(stdout, "Search smoke GPU finish: frames=%zu p95_ms=%.6f max_ms=%.6f\n",
                         gpuWaits.size(), gpuWaits[std::ceil(gpuWaits.size() * 0.95) - 1],
                         gpuWaits.back());
            std::fflush(stdout);
        }
        event->type = SDL_QUIT;
    }
    else if (action == "text" || action == "compose") {
        event->type = action == "text" ? SDL_TEXTINPUT : SDL_TEXTEDITING;
        SDL_strlcpy(event->text.text, value.c_str(), sizeof(event->text.text));
    }
    else if (action == "pad" || action == "pad-typing" || action == "pad-pending-text") {
        typeWhileOpening = action == "pad-typing";
        if (controller < 0)
            std::abort();
        event->type = SDL_CONTROLLERBUTTONDOWN;
        event->cbutton.which = controller;
        event->cbutton.button = static_cast<Uint8>(std::stoi(value));
        event->cbutton.state = SDL_PRESSED;
        release = *event;
        release.type = SDL_CONTROLLERBUTTONUP;
        release.cbutton.state = SDL_RELEASED;
        if (action == "pad-pending-text") {
            // Model native commits already queued behind Y while browsing accepts
            // text. The screen must retain them when it takes over the input field.
            SDL_EventState(SDL_TEXTINPUT, SDL_ENABLE);
            SDL_Event text {};
            text.type = SDL_TEXTINPUT;
            SDL_strlcpy(text.text.text, "fin", sizeof(text.text.text));
            SDL_PushEvent(&text);
        }
    }
    else if (action == "key" || action == "key-text" || action == "text-key") {
        std::istringstream key(value);
        int symbol {0}, modifier {0};
        key >> symbol >> modifier;
        SDL_SetModState(static_cast<SDL_Keymod>(modifier));
        event->type = SDL_KEYDOWN;
        event->key.keysym.sym = symbol;
        event->key.keysym.mod = modifier;
        release = *event;
        release.type = SDL_KEYUP;
        if (action != "key") {
            std::string text;
            std::getline(key, text);
            if (!text.empty() && text.front() == ' ')
                text.erase(0, 1);
            queued.type = SDL_TEXTINPUT;
            SDL_strlcpy(queued.text.text, text.c_str(), sizeof(queued.text.text));
            // Desktop normally commits after key-down; Android commits before it.
            if (action == "text-key")
                std::swap(*event, queued);
        }
    }
    acknowledge();
    return event->type ? 1 : 0;
}
