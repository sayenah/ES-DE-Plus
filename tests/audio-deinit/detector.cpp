//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  detector.cpp
//
//  Written for ES-DE-Plus. Interpose application SDL calls to detect freed-stream reads
//  before entering uninstrumented SDL. SDL's internal dynapi calls remain untouched.
//

#include "AudioManager.h"
#include "Sound.h"

#include <SDL2/SDL.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <mutex>
#include <unordered_set>
#include <vector>

namespace
{
    constexpr int detectedExit {86};
    std::atomic<bool> armed {false};
    std::atomic<unsigned> gets {0};
    std::atomic<unsigned> audibleMixes {0};
    std::mutex freedMutex;
    std::unordered_set<SDL_AudioStream*> freed;
    unsigned windowMs {70};

    void require(bool condition, const char* message)
    {
        if (!condition) {
            std::fprintf(stderr, "FAIL: %s (%s)\n", message, SDL_GetError());
            std::exit(1);
        }
    }

    template <typename Function> Function real(const char* name)
    {
        void* symbol {dlsym(RTLD_NEXT, name)};
        require(symbol != nullptr, name);
        return reinterpret_cast<Function>(symbol);
    }

    void check(SDL_AudioStream* stream, const char* operation)
    {
        std::lock_guard<std::mutex> lock {freedMutex};
        if (stream && freed.count(stream)) {
            std::fprintf(stderr, "DETECTED: %s on freed stream %p\n", operation,
                         static_cast<void*>(stream));
            // Do not forward the invalid pointer or attempt teardown from the callback.
            std::_Exit(detectedExit);
        }
    }

    void widen()
    {
        if (armed)
            SDL_Delay(windowMs);
    }
} // namespace

extern "C" void SDLCALL SDL_FreeAudioStream(SDL_AudioStream* stream)
{
    static auto forward {real<decltype(&SDL_FreeAudioStream)>("SDL_FreeAudioStream")};
    if (armed && stream) {
        std::lock_guard<std::mutex> lock {freedMutex};
        freed.insert(stream);
    }
    forward(stream);
}

extern "C" int SDLCALL SDL_AudioStreamAvailable(SDL_AudioStream* stream)
{
    static auto forward {real<decltype(&SDL_AudioStreamAvailable)>("SDL_AudioStreamAvailable")};
    check(stream, "SDL_AudioStreamAvailable");
    return forward(stream);
}

extern "C" int SDLCALL SDL_AudioStreamGet(SDL_AudioStream* stream, void* buffer, int length)
{
    static auto forward {real<decltype(&SDL_AudioStreamGet)>("SDL_AudioStreamGet")};
    check(stream, "SDL_AudioStreamGet");
    int result {forward(stream, buffer, length)};
    if (result > 0)
        ++gets;
    return result;
}

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

extern "C" void SDLCALL SDL_UnlockAudioDevice(SDL_AudioDeviceID device)
{
    static auto forward {real<decltype(&SDL_UnlockAudioDevice)>("SDL_UnlockAudioDevice")};
    forward(device);
    widen();
}

extern "C" void SDLCALL SDL_CloseAudioDevice(SDL_AudioDeviceID device)
{
    static auto forward {real<decltype(&SDL_CloseAudioDevice)>("SDL_CloseAudioDevice")};
    widen();
    forward(device);
}

extern "C" void SDLCALL SDL_QuitSubSystem(Uint32 flags)
{
    static auto forward {real<decltype(&SDL_QuitSubSystem)>("SDL_QuitSubSystem")};
    widen();
    forward(flags);
}

int main(int argc, char* argv[])
{
    require(argc == 4, "usage: audio-deinit armed|disarmed cycles navigation.wav");
    const bool widenWindows {std::strcmp(argv[1], "armed") == 0};
    require(widenWindows || std::strcmp(argv[1], "disarmed") == 0, "valid mode");
    const int cycles {std::atoi(argv[2])};
    require(cycles > 0, "positive cycle count");
    SDL_version version;
    SDL_GetVersion(&version);
    std::printf("SDL %u.%u.%u; mode=%s; cycles=%i\n", version.major, version.minor, version.patch,
                argv[1], cycles);
    std::fflush(stdout); // The positive control exits from the callback with _Exit.
    auto& manager = AudioManager::getInstance();
    for (int cycle {0}; cycle < cycles; ++cycle) {
        if (cycle)
            manager.init();
        require(AudioManager::sAudioDevice >= 2, "real audio device opened");
        windowMs =
            3 * 1000 * AudioManager::sAudioFormat.samples / AudioManager::sAudioFormat.freq + 1;
        // Only clear retired addresses after the preceding close has joined its callback.
        {
            std::lock_guard<std::mutex> lock {freedMutex};
            freed.clear();
        }
        auto sound {Sound::get(argv[3])};
        require(sound->getLength() > 0, "actual navigation WAV loaded");
        const unsigned priorMixes {audibleMixes};
        sound->play();
        const Uint32 navigationDeadline {SDL_GetTicks() + 1000};
        while (audibleMixes == priorMixes && SDL_GetTicks() < navigationDeadline)
            SDL_Delay(1);
        require(audibleMixes > priorMixes, "navigation samples mixed after init/reinit");
        sound->stop();
        const unsigned priorGets {gets};
        const unsigned priorVideoMixes {audibleMixes};
        // One second of continuous video-format samples keeps the callback unpaused
        // through the three-period teardown windows, without another producer thread.
        std::vector<float> samples(44100 * 2, 0.125f);
        manager.processStream(samples.data(), samples.size() * sizeof(float));
        const Uint32 videoDeadline {SDL_GetTicks() + 1000};
        while ((gets == priorGets || audibleMixes == priorVideoMixes) &&
               SDL_GetTicks() < videoDeadline)
            SDL_Delay(1);
        require(gets > priorGets && audibleMixes > priorVideoMixes,
                "video stream read and non-silent samples mixed after init/reinit");
        require(SDL_GetAudioDeviceStatus(AudioManager::sAudioDevice) == SDL_AUDIO_PLAYING,
                "device unpaused at teardown");
        armed = widenWindows;
        manager.deinit();
        armed = false;
        if (widenWindows) {
            std::lock_guard<std::mutex> lock {freedMutex};
            require(!freed.empty(), "armed teardown recorded the released conversion stream");
        }
        require(AudioManager::sAudioDevice == 0, "device id cleared");
        manager.deinit(); // Idempotent early return.
        // Real main-thread callers during Window::deinit, before the next init.
        sound->play();
        sound->stop();
        manager.play();
        manager.stop();
        manager.clearStream();
        manager.processStream(samples.data(), 0);
        manager.unregisterSound(sound);
        sound->deinit();
    }
    // Match desktop Renderer shutdown before the AudioManager static destructor.
    manager.init();
    SDL_Quit();
    std::printf(
        "PASS: %i cycles; freed-stream reads=0; real navigation/video mixing; desktop exit\n",
        cycles);
}
