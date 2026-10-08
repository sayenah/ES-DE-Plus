//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  PlatformUtilAndroid.h
//
//  Open Android platform bridge for the ES-DE frontend.
//
//  This interface is derived from the public ES-DE C++ call sites. The implementation in
//  ES-DE-Plus is independent from the proprietary Android host used by official ES-DE builds.
//

#ifndef ES_CORE_UTILS_PLATFORM_UTIL_ANDROID_H
#define ES_CORE_UTILS_PLATFORM_UTIL_ANDROID_H

#include <atomic>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace AndroidVariables
{
    extern std::atomic<bool> sHold;
    extern std::atomic<bool> sIsHomeApp;
    extern std::atomic<bool> sResetTouchOverlay;

    extern std::string sExternalDataDirectory;
    extern std::string sInternalDataDirectory;
    extern std::string sROMDirectory;
} // namespace AndroidVariables

namespace Utils
{
    namespace Platform
    {
        namespace Android
        {
            bool checkConfigurationNeeded();
            bool checkEmulatorInstalled(const std::string& packageName,
                                        const std::string& activityName);
            bool checkNeedResourceCopy(const std::string& buildIdentifier);
            int checkRACoreInstalled(const std::string& packageName, const std::string& coreFile);

            std::pair<int, int> getBatteryStatus();
            int getBluetoothStatus();
            int getCellularStatus();
            bool getCreateSystemDirectories();
            std::string getExternalDirectory();
            void getInstalledApps(std::vector<std::pair<std::string, std::string>>& appList,
                                  bool gamesOnly,
                                  bool includeMedia);
            std::string getInternalDirectory();
            int getWifiStatus();
            std::pair<int, int> getWindowSize();

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
                           bool launchOnOtherScreen);

            void onResume();
            void printDeviceInfo();
            void setDataDirectories();
            void setROMDirectory();
            void setupFontFiles();
            void setupLocalizationFiles();
            bool setupResources(const std::string& buildIdentifier);
            void startConfigurator();
        } // namespace Android
    } // namespace Platform
} // namespace Utils

#endif // ES_CORE_UTILS_PLATFORM_UTIL_ANDROID_H
