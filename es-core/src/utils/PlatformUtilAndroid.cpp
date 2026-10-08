//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  PlatformUtilAndroid.cpp
//
//  Clean-room Android platform bridge implemented against the public ES-DE C++ callers and
//  public Android/SDL APIs.
//

#include "utils/PlatformUtilAndroid.h"

#if defined(__ANDROID__)

#include "Log.h"
#include "utils/FileSystemUtil.h"

#include <SDL2/SDL_system.h>
#include <jni.h>

#include "utf8.h"
#include <array>

namespace AndroidVariables
{
    std::atomic<bool> sHold {false};
    std::atomic<bool> sIsHomeApp {false};
    std::atomic<bool> sResetTouchOverlay {false};

    std::string sExternalDataDirectory;
    std::string sInternalDataDirectory;
    std::string sROMDirectory;
} // namespace AndroidVariables

namespace
{
    struct ActivityContext {
        JNIEnv* env {nullptr};
        jobject activity {nullptr};
        jclass activityClass {nullptr};
        bool frame {false};

        ActivityContext()
        {
            env = static_cast<JNIEnv*>(SDL_AndroidGetJNIEnv());
            if (env == nullptr)
                return;

            if (env->ExceptionCheck()) {
                env->ExceptionDescribe();
                env->ExceptionClear();
                return;
            }
            frame = env->PushLocalFrame(64) == JNI_OK;
            if (!frame) {
                env->ExceptionClear();
                return;
            }

            activity = SDL_AndroidGetActivity();
            if (activity == nullptr)
                return;

            activityClass = env->GetObjectClass(activity);
            if (env->ExceptionCheck()) {
                env->ExceptionDescribe();
                env->ExceptionClear();
                activityClass = nullptr;
            }
        }

        ~ActivityContext()
        {
            if (env != nullptr && frame) {
                if (env->ExceptionCheck()) {
                    env->ExceptionDescribe();
                    env->ExceptionClear();
                }
                env->PopLocalFrame(nullptr);
            }
        }

        explicit operator bool() const
        {
            return env != nullptr && activity != nullptr && activityClass != nullptr;
        }
    };

    bool clearJavaException(JNIEnv* env, const char* method)
    {
        if (env == nullptr || !env->ExceptionCheck())
            return false;

        LOG(LogError) << "Android bridge: Java exception while calling " << method;
        env->ExceptionDescribe();
        env->ExceptionClear();
        return true;
    }

    jmethodID getMethod(ActivityContext& context, const char* method, const char* signature)
    {
        if (!context)
            return nullptr;

        jmethodID id {context.env->GetMethodID(context.activityClass, method, signature)};
        if (id == nullptr)
            clearJavaException(context.env, method);
        return id;
    }

    jstring toJString(JNIEnv* env, const std::string& value)
    {
        std::u16string converted;
        try {
            utf8::utf8to16(value.begin(), value.end(), std::back_inserter(converted));
        }
        catch (const std::exception& error) {
            LOG(LogError) << "Android bridge: invalid UTF-8: " << error.what();
            return nullptr;
        }
        return env->NewString(reinterpret_cast<const jchar*>(converted.data()),
                              static_cast<jsize>(converted.size()));
    }

    std::string fromJString(JNIEnv* env, jstring value)
    {
        if (env == nullptr || value == nullptr)
            return {};
        const jsize length {env->GetStringLength(value)};
        if (clearJavaException(env, "GetStringLength"))
            return {};
        const jchar* chars {env->GetStringChars(value, nullptr)};
        if (clearJavaException(env, "GetStringChars") || chars == nullptr)
            return {};
        std::string result;
        try {
            utf8::utf16to8(chars, chars + length, std::back_inserter(result));
        }
        catch (const std::exception& error) {
            LOG(LogError) << "Android bridge: invalid UTF-16: " << error.what();
        }
        env->ReleaseStringChars(value, chars);
        return result;
    }

    jobjectArray toStringArray(JNIEnv* env, const std::vector<std::string>& values)
    {
        jclass stringClass {env->FindClass("java/lang/String")};
        if (clearJavaException(env, "FindClass") || stringClass == nullptr)
            return nullptr;

        jobjectArray array {
            env->NewObjectArray(static_cast<jsize>(values.size()), stringClass, nullptr)};

        if (clearJavaException(env, "NewObjectArray") || array == nullptr)
            return nullptr;

        for (size_t i {0}; i < values.size(); ++i) {
            jstring value {toJString(env, values[i])};
            if (clearJavaException(env, "NewString") || value == nullptr)
                return nullptr;
            env->SetObjectArrayElement(array, static_cast<jsize>(i), value);
            if (clearJavaException(env, "SetObjectArrayElement"))
                return nullptr;
            env->DeleteLocalRef(value);
        }

        env->DeleteLocalRef(stringClass);
        return array;
    }

    jobjectArray toStringArray(JNIEnv* env, const std::map<std::string, std::string>& values)
    {
        std::vector<std::string> flattened;
        flattened.reserve(values.size() * 2);
        for (const auto& entry : values) {
            flattened.emplace_back(entry.first);
            flattened.emplace_back(entry.second);
        }
        return toStringArray(env, flattened);
    }

    bool callBool(const char* method, bool fallback = false)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()Z")};
        if (id == nullptr)
            return fallback;

        const jboolean result {context.env->CallBooleanMethod(context.activity, id)};
        if (clearJavaException(context.env, method))
            return fallback;
        return result == JNI_TRUE;
    }

    bool callBool(const char* method, const std::string& arg, bool fallback = false)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "(Ljava/lang/String;)Z")};
        if (id == nullptr)
            return fallback;

        jstring value {toJString(context.env, arg)};
        if (clearJavaException(context.env, method) || value == nullptr)
            return fallback;
        const jboolean result {context.env->CallBooleanMethod(context.activity, id, value)};
        context.env->DeleteLocalRef(value);
        if (clearJavaException(context.env, method))
            return fallback;
        return result == JNI_TRUE;
    }

    int callInt(const char* method, int fallback = 0)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()I")};
        if (id == nullptr)
            return fallback;

        const jint result {context.env->CallIntMethod(context.activity, id)};
        if (clearJavaException(context.env, method))
            return fallback;
        return static_cast<int>(result);
    }

    int callInt(const char* method,
                const std::string& first,
                const std::string& second,
                int fallback)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "(Ljava/lang/String;Ljava/lang/String;)I")};
        if (id == nullptr)
            return fallback;

        jstring firstValue {toJString(context.env, first)};
        if (clearJavaException(context.env, method) || firstValue == nullptr)
            return fallback;
        jstring secondValue {toJString(context.env, second)};
        if (clearJavaException(context.env, method) || secondValue == nullptr)
            return fallback;
        const jint result {
            context.env->CallIntMethod(context.activity, id, firstValue, secondValue)};
        context.env->DeleteLocalRef(firstValue);
        context.env->DeleteLocalRef(secondValue);
        if (clearJavaException(context.env, method))
            return fallback;
        return static_cast<int>(result);
    }

    std::string callString(const char* method)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()Ljava/lang/String;")};
        if (id == nullptr)
            return {};

        jstring value {static_cast<jstring>(context.env->CallObjectMethod(context.activity, id))};
        if (clearJavaException(context.env, method))
            return {};

        std::string result {fromJString(context.env, value)};
        if (value != nullptr)
            context.env->DeleteLocalRef(value);
        return result;
    }

    std::pair<int, int> callIntPair(const char* method, const std::pair<int, int>& fallback)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()[I")};
        if (id == nullptr)
            return fallback;

        jintArray values {
            static_cast<jintArray>(context.env->CallObjectMethod(context.activity, id))};
        if (clearJavaException(context.env, method))
            return fallback;
        const jsize size {values == nullptr ? 0 : context.env->GetArrayLength(values)};
        if (clearJavaException(context.env, method))
            return fallback;
        if (values == nullptr || size < 2) {
            if (values != nullptr)
                context.env->DeleteLocalRef(values);
            return fallback;
        }

        std::array<jint, 2> result {};
        context.env->GetIntArrayRegion(values, 0, 2, result.data());
        if (clearJavaException(context.env, method))
            return fallback;
        context.env->DeleteLocalRef(values);
        return {static_cast<int>(result[0]), static_cast<int>(result[1])};
    }

    void callVoid(const char* method)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()V")};
        if (id == nullptr)
            return;

        context.env->CallVoidMethod(context.activity, id);
        clearJavaException(context.env, method);
    }
} // namespace

namespace Utils
{
    namespace Platform
    {
        namespace Android
        {
            bool checkConfigurationNeeded() { return callBool("checkConfigurationNeeded", true); }

            bool checkEmulatorInstalled(const std::string& packageName,
                                        const std::string& activityName)
            {
                ActivityContext context;
                jmethodID id {getMethod(context, "checkEmulatorInstalled",
                                        "(Ljava/lang/String;Ljava/lang/String;)Z")};
                if (id == nullptr)
                    return false;

                jstring packageValue {toJString(context.env, packageName)};
                if (clearJavaException(context.env, "checkEmulatorInstalled") ||
                    packageValue == nullptr)
                    return false;
                jstring activityValue {toJString(context.env, activityName)};
                if (clearJavaException(context.env, "checkEmulatorInstalled") ||
                    activityValue == nullptr)
                    return false;
                const jboolean result {context.env->CallBooleanMethod(context.activity, id,
                                                                      packageValue, activityValue)};
                context.env->DeleteLocalRef(packageValue);
                context.env->DeleteLocalRef(activityValue);
                if (clearJavaException(context.env, "checkEmulatorInstalled"))
                    return false;
                return result == JNI_TRUE;
            }

            bool checkNeedResourceCopy(const std::string& buildIdentifier)
            {
                return callBool("checkNeedResourceCopy", buildIdentifier, true);
            }

            int checkRACoreInstalled(const std::string& packageName, const std::string& coreFile)
            {
                return callInt("checkRACoreInstalled", packageName, coreFile, -2);
            }

            std::pair<int, int> getBatteryStatus()
            {
                return callIntPair("getBatteryStatus", {-1, -1});
            }

            int getBluetoothStatus() { return callInt("getBluetoothStatus"); }

            int getCellularStatus() { return callInt("getCellularStatus"); }

            bool getCreateSystemDirectories() { return callBool("getCreateSystemDirectories"); }

            std::string getExternalDirectory() { return callString("getExternalDirectory"); }

            void getInstalledApps(std::vector<std::pair<std::string, std::string>>& appList,
                                  bool gamesOnly,
                                  bool includeMedia)
            {
                appList.clear();

                ActivityContext context;
                jmethodID id {getMethod(context, "getInstalledApps", "(ZZ)[Ljava/lang/String;")};
                if (id == nullptr)
                    return;

                jobjectArray values {static_cast<jobjectArray>(context.env->CallObjectMethod(
                    context.activity, id, gamesOnly ? JNI_TRUE : JNI_FALSE,
                    includeMedia ? JNI_TRUE : JNI_FALSE))};
                if (clearJavaException(context.env, "getInstalledApps"))
                    return;

                if (values == nullptr)
                    return;

                const jsize size {context.env->GetArrayLength(values)};
                if (clearJavaException(context.env, "getInstalledApps"))
                    return;
                for (jsize i {0}; i + 1 < size; i += 2) {
                    jstring displayName {
                        static_cast<jstring>(context.env->GetObjectArrayElement(values, i))};
                    if (clearJavaException(context.env, "getInstalledApps")) {
                        appList.clear();
                        return;
                    }
                    jstring packageName {
                        static_cast<jstring>(context.env->GetObjectArrayElement(values, i + 1))};

                    if (clearJavaException(context.env, "getInstalledApps")) {
                        appList.clear();
                        return;
                    }
                    appList.emplace_back(fromJString(context.env, displayName),
                                         fromJString(context.env, packageName));

                    if (displayName != nullptr)
                        context.env->DeleteLocalRef(displayName);
                    if (packageName != nullptr)
                        context.env->DeleteLocalRef(packageName);
                }

                context.env->DeleteLocalRef(values);
            }

            std::string getInternalDirectory() { return callString("getInternalDirectory"); }

            int getWifiStatus() { return callInt("getWifiStatus"); }

            std::pair<int, int> getWindowSize() { return callIntPair("getWindowSize", {0, 0}); }

            int launchGame(const std::string& packageName,
                           const std::string& activityName,
                           const std::string& action,
                           const std::string& category,
                           const std::string& mimeType,
                           const std::string& data,
                           const std::string& startPath,
                           const std::string& romPath,
                           const std::map<std::string, std::string>& extrasString,
                           const std::map<std::string, std::string>& extrasStringArray,
                           const std::map<std::string, std::string>& extrasInteger,
                           const std::map<std::string, std::string>& extrasBool,
                           const std::vector<std::string>& activityFlags,
                           bool launchOnOtherScreen)
            {
                ActivityContext context;
                jmethodID id {
                    getMethod(context, "launchGame",
                              "([Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;"
                              "[Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;Z)I")};
                if (id == nullptr)
                    return -1;

                const std::vector<std::string> baseArguments {packageName, activityName, action,
                                                              category,    mimeType,     data,
                                                              startPath,   romPath};

                jobjectArray baseArray {toStringArray(context.env, baseArguments)};
                if (clearJavaException(context.env, "launchGame") || baseArray == nullptr)
                    return -1;
                jobjectArray stringArray {toStringArray(context.env, extrasString)};
                if (clearJavaException(context.env, "launchGame") || stringArray == nullptr)
                    return -1;
                jobjectArray stringListArray {toStringArray(context.env, extrasStringArray)};
                if (clearJavaException(context.env, "launchGame") || stringListArray == nullptr)
                    return -1;
                jobjectArray integerArray {toStringArray(context.env, extrasInteger)};
                if (clearJavaException(context.env, "launchGame") || integerArray == nullptr)
                    return -1;
                jobjectArray boolArray {toStringArray(context.env, extrasBool)};
                if (clearJavaException(context.env, "launchGame") || boolArray == nullptr)
                    return -1;
                jobjectArray flagArray {toStringArray(context.env, activityFlags)};
                if (clearJavaException(context.env, "launchGame") || flagArray == nullptr)
                    return -1;

                const jint result {context.env->CallIntMethod(
                    context.activity, id, baseArray, stringArray, stringListArray, integerArray,
                    boolArray, flagArray, launchOnOtherScreen ? JNI_TRUE : JNI_FALSE)};

                context.env->DeleteLocalRef(baseArray);
                context.env->DeleteLocalRef(stringArray);
                context.env->DeleteLocalRef(stringListArray);
                context.env->DeleteLocalRef(integerArray);
                context.env->DeleteLocalRef(boolArray);
                context.env->DeleteLocalRef(flagArray);
                if (clearJavaException(context.env, "launchGame"))
                    return -1;

                return static_cast<int>(result);
            }

            void onResume() { callVoid("onNativeFrontendResume"); }

            void printDeviceInfo()
            {
                ActivityContext context;
                jmethodID id {getMethod(context, "getDeviceInfo", "()Ljava/lang/String;")};
                if (id == nullptr)
                    return;

                jstring value {
                    static_cast<jstring>(context.env->CallObjectMethod(context.activity, id))};
                if (clearJavaException(context.env, "getDeviceInfo"))
                    return;
                const std::string info {fromJString(context.env, value)};
                if (value != nullptr)
                    context.env->DeleteLocalRef(value);

                if (!info.empty())
                    LOG(LogDebug) << "Android device: " << info;
            }

            void setDataDirectories()
            {
                AndroidVariables::sInternalDataDirectory = callString("getInternalDataDirectory");
                AndroidVariables::sExternalDataDirectory = callString("getAppDataDirectory");

                if (AndroidVariables::sExternalDataDirectory.empty())
                    AndroidVariables::sExternalDataDirectory =
                        AndroidVariables::sInternalDataDirectory;

                FileSystemVariables::sAppDataDirectory = AndroidVariables::sExternalDataDirectory;
            }

            void setROMDirectory()
            {
                AndroidVariables::sROMDirectory = callString("getROMDirectory");
            }

            void setupFontFiles() { callVoid("setupFontFiles"); }

            void setupLocalizationFiles() { callVoid("setupLocalizationFiles"); }

            bool setupResources(const std::string& buildIdentifier)
            {
                // The frontend's existing caller interprets true as a copy failure.
                return callBool("setupResources", buildIdentifier, true);
            }

            void startConfigurator()
            {
                AndroidVariables::sHold = true;
                callVoid("startConfigurator");
                AndroidVariables::sHold = false;
            }
        } // namespace Android
    } // namespace Platform
} // namespace Utils

extern "C" JNIEXPORT void JNICALL
Java_org_esdeplus_frontend_MainActivity_nativeSetHold(JNIEnv*, jclass, jboolean hold)
{
    AndroidVariables::sHold = hold == JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_org_esdeplus_frontend_MainActivity_nativeSetHomeApp(JNIEnv*, jclass, jboolean isHomeApp)
{
    AndroidVariables::sIsHomeApp = isHomeApp == JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_org_esdeplus_frontend_MainActivity_nativeSetResetTouchOverlay(JNIEnv*, jclass, jboolean reset)
{
    AndroidVariables::sResetTouchOverlay = reset == JNI_TRUE;
}

#if !defined(NDEBUG)
// CI runtime probe exercises the production bridge; it does not replace its results.
extern "C" JNIEXPORT jboolean JNICALL Java_org_esdeplus_frontend_RuntimeSmoke_nativeProbe(
    JNIEnv* env, jclass, jstring directory, jstring game)
{
    ActivityContext context;
    if (!context)
        return JNI_FALSE;
    const std::pair<const char*, const char*> methods[] {
        {"checkConfigurationNeeded", "()Z"},
        {"checkEmulatorInstalled", "(Ljava/lang/String;Ljava/lang/String;)Z"},
        {"checkNeedResourceCopy", "(Ljava/lang/String;)Z"},
        {"checkRACoreInstalled", "(Ljava/lang/String;Ljava/lang/String;)I"},
        {"getBatteryStatus", "()[I"},
        {"getBluetoothStatus", "()I"},
        {"getCellularStatus", "()I"},
        {"getCreateSystemDirectories", "()Z"},
        {"getExternalDirectory", "()Ljava/lang/String;"},
        {"getInstalledApps", "(ZZ)[Ljava/lang/String;"},
        {"getInternalDirectory", "()Ljava/lang/String;"},
        {"getWifiStatus", "()I"},
        {"getWindowSize", "()[I"},
        {"getDeviceInfo", "()Ljava/lang/String;"},
        {"getInternalDataDirectory", "()Ljava/lang/String;"},
        {"getAppDataDirectory", "()Ljava/lang/String;"},
        {"getROMDirectory", "()Ljava/lang/String;"},
        {"setupFontFiles", "()V"},
        {"setupLocalizationFiles", "()V"},
        {"setupResources", "(Ljava/lang/String;)Z"},
        {"startConfigurator", "()V"},
        {"onNativeFrontendResume", "()V"},
        {"launchGame", "([Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;"
                       "[Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;Z)I"}};
    for (const auto& method : methods) {
        if (getMethod(context, method.first, method.second) == nullptr)
            return JNI_FALSE;
    }
    for (int i {0}; i < 10000; ++i) {
        const auto size {Utils::Platform::Android::getWindowSize()};
        if (size.first <= 0 || size.second <= 0 || env->ExceptionCheck())
            return JNI_FALSE;
    }
    for (jstring path : {directory, game}) {
        const std::string original {fromJString(env, path)};
        jstring converted {toJString(env, original)};
        if (clearJavaException(env, "Unicode probe") || converted == nullptr)
            return JNI_FALSE;
        const std::string roundtrip {fromJString(env, converted)};
        env->DeleteLocalRef(converted);
        if (roundtrip != original || !Utils::FileSystem::exists(roundtrip))
            return JNI_FALSE;
    }
    using namespace Utils::Platform::Android;
    std::vector<std::pair<std::string, std::string>> apps;
    getInstalledApps(apps, false, false);
    if (checkConfigurationNeeded() || checkEmulatorInstalled("", "") ||
        checkRACoreInstalled("", "") != -2 || !apps.empty() || getBluetoothStatus() != 0 ||
        getWifiStatus() != 0 || getCellularStatus() != 0 ||
        getBatteryStatus() != std::make_pair(-1, -1))
        return JNI_FALSE;
    if (getInternalDirectory().find("/data/user/") != 0 ||
        getExternalDirectory().find("/storage/emulated/") != 0)
        return JNI_FALSE;
    if (launchGame("", "", "", "", "", "", "", "", {}, {}, {}, {}, {}, false) == 0)
        return JNI_FALSE;
    startConfigurator();
    onResume();
    if (AndroidVariables::sHold || env->ExceptionCheck())
        return JNI_FALSE;
    LOG(LogInfo) << "Android bridge runtime probe passed: 10000 calls, UTF-16 and sentinels";
    return JNI_TRUE;
}
#endif

#endif // __ANDROID__
