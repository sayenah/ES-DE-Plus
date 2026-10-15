//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  desktop.cpp
//
//  Written for ES-DE-Plus. SDL input/output probe for the actual desktop frontend.
//  Loaded only by desktop.py; no production code or dependency is substituted.
//

#include <SDL2/SDL.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <string>

namespace
{
    std::atomic<unsigned> audibleMixes {0};

    template <typename Function> Function real(const char* name)
    {
        void* symbol {dlsym(RTLD_NEXT, name)};
        if (!symbol)
            std::abort();
        return reinterpret_cast<Function>(symbol);
    }
} // namespace

extern "C" void SDLCALL
SDL_MixAudioFormat(Uint8* dst, const Uint8* src, SDL_AudioFormat format, Uint32 length, int volume)
{
    static auto forward {real<decltype(&SDL_MixAudioFormat)>("SDL_MixAudioFormat")};
    forward(dst, src, format, length, volume);
    if (volume && format == AUDIO_F32) {
        for (Uint32 offset {0}; offset + sizeof(float) <= length; offset += sizeof(float)) {
            float sample;
            std::memcpy(&sample, dst + offset, sizeof(sample));
            if (sample != 0.0f) {
                ++audibleMixes;
                break;
            }
        }
    }
}

extern "C" int SDLCALL SDL_PollEvent(SDL_Event* event)
{
    static auto forward {real<decltype(&SDL_PollEvent)>("SDL_PollEvent")};
    static unsigned last {0};
    static SDL_Keycode release {0};
    if (!event)
        return forward(event);
    if (release) {
        SDL_zero(*event);
        event->type = SDL_KEYUP;
        event->key.keysym.sym = release;
        release = 0;
        return 1;
    }
    // Commands and acknowledgements are outside user data, in this test's build dir.
    const std::string directory {std::getenv("ESDE_AUDIO_PROBE")};
    unsigned sequence {0};
    std::string action;
    std::ifstream(directory + "/command") >> sequence >> action;
    if (sequence > last) {
        last = sequence;
        {
            std::ofstream(directory + "/ack.new") << sequence << " " << audibleMixes << "\n";
        }
        std::rename((directory + "/ack.new").c_str(), (directory + "/ack").c_str());
        SDL_zero(*event);
        if (action == "quit") {
            event->type = SDL_QUIT;
            return 1;
        }
        SDL_Keycode key {0};
        if (action == "enter")
            key = SDLK_RETURN;
        else if (action == "down")
            key = SDLK_DOWN;
        else if (action == "up")
            key = SDLK_UP;
        if (key) {
            event->type = SDL_KEYDOWN;
            event->key.keysym.sym = key;
            release = key;
            return 1;
        }
    }
    return forward(event);
}
