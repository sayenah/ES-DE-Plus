//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ConvertPDF.cpp
//
//  Written for ES-DE-Plus from D-008, the MIT consumers and public SDL/Android APIs.
//  No upstream GPL converter implementation is used.
//

#include "ConvertPDF.h"

#if defined(__ANDROID__)
#include <SDL2/SDL_system.h>
#include <android/log.h>
#include <jni.h>
#include <mutex>
#include <new>
#include <utf8.h>

namespace
{
    // Also serialises JNI marshalling. The host serialises renderer ownership independently.
    std::mutex sConversionMutex;

    bool failed(JNIEnv* env)
    {
        if (!env->ExceptionCheck())
            return false;
        env->ExceptionDescribe();
        env->ExceptionClear();
        return true;
    }

    struct LocalFrame {
        JNIEnv* env;
        ~LocalFrame()
        {
            env->PopLocalFrame(nullptr);
            failed(env);
        }
    };
} // namespace

int ConvertPDF::processFile(const std::string path,
                            const std::string mode,
                            int pageNum,
                            int width,
                            int height,
                            std::string& result)
{
    result.clear();
    const bool info {mode == "-fileinfo"};
    if (path.empty() || path.front() != '/' || path.find('\0') != std::string::npos ||
        (!info && mode != "-convert") || (info && (pageNum != 0 || width != 0 || height != 0)) ||
        (!info && (pageNum < 1 || width < 1 || height < 1 || width > 4096 || height > 4096 ||
                   static_cast<int64_t>(width) * height * 4 > 32 * 1024 * 1024)))
        return -1;

    std::u16string utf16;
    try {
        utf8::utf8to16(path.begin(), path.end(), std::back_inserter(utf16));
    }
    catch (const std::exception&) {
        return -1;
    }
    std::lock_guard<std::mutex> lock {sConversionMutex};
    auto* env = static_cast<JNIEnv*>(SDL_AndroidGetJNIEnv());
    if (env == nullptr || failed(env))
        return -1;
    if (env->PushLocalFrame(16) != JNI_OK) {
        failed(env);
        return -1;
    }
    LocalFrame frame {env};
    jobject activity {static_cast<jobject>(SDL_AndroidGetActivity())};
    if (failed(env) || activity == nullptr)
        return -1;
    jclass type {env->GetObjectClass(activity)};
    if (failed(env) || type == nullptr)
        return -1;
    jmethodID method {env->GetMethodID(type, info ? "getPdfPageInfo" : "renderPdfPage",
                                       info ? "(Ljava/lang/String;)Ljava/lang/String;" :
                                              "(Ljava/lang/String;III)[B")};
    if (failed(env) || method == nullptr)
        return -1;
    jstring filename {env->NewString(reinterpret_cast<const jchar*>(utf16.data()),
                                     static_cast<jsize>(utf16.size()))};
    if (failed(env) || filename == nullptr)
        return -1;
    jobject output {info ?
                        env->CallObjectMethod(activity, method, filename) :
                        env->CallObjectMethod(activity, method, filename, pageNum, width, height)};
    if (failed(env) || output == nullptr)
        return -1;

    std::string converted;
    const jsize length {info ? env->GetStringLength(static_cast<jstring>(output)) :
                               env->GetArrayLength(static_cast<jbyteArray>(output))};
    if (failed(env) || length == 0 || (!info && length != static_cast<int64_t>(width) * height * 4))
        return -1;
    // Allocate before pinning Java characters, so a native allocation failure
    // also returns an empty result and cannot retain a pinned JNI buffer.
    try {
        converted.resize(length);
    }
    catch (const std::bad_alloc&) {
        return -1;
    }
    if (info) {
        auto value = static_cast<jstring>(output);
        const jchar* characters {env->GetStringChars(value, nullptr)};
        if (failed(env) || characters == nullptr)
            return -1;
        // Metadata contains only locale-independent ASCII (D-008).
        bool valid {true};
        for (jsize i {0}; i < length; ++i) {
            if (characters[i] > 127)
                valid = false;
            converted[i] = static_cast<char>(characters[i]);
        }
        env->ReleaseStringChars(value, characters);
        if (failed(env) || !valid)
            return -1;
    }
    else {
        auto bytes = static_cast<jbyteArray>(output);
        env->GetByteArrayRegion(bytes, 0, length, reinterpret_cast<jbyte*>(converted.data()));
        if (failed(env))
            return -1;
    }
    result.swap(converted);
    return 0;
}
#endif
