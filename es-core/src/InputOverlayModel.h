//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  InputOverlayModel.h
//
//  Written for ES-DE-Plus from the open input contract and MIT overlay assets.
//  Platform-independent geometry, gesture epochs and input transitions; no GPU ownership.
//

#ifndef ES_CORE_INPUT_OVERLAY_MODEL_H
#define ES_CORE_INPUT_OVERLAY_MODEL_H

#include <array>
#include <cstdint>
#include <string_view>

namespace TouchOverlay
{
    constexpr int NO_BUTTON {-2};
    constexpr std::array<int, 14> IDS {11, 12, 13, 14, 0, 1, 2, 3, 4, 6, 9, 10, 100, 101};

    struct Point {
        float x {0};
        float y {0};
    };

    struct Rect {
        float x {0};
        float y {0};
        float w {0};
        float h {0};
        bool contains(Point p, float expansion = 1.0f) const;
    };

    // Renderer-owned viewport, including its top-left Y convention. Drawable dimensions
    // are sampled together with it, never from transient postprocessing GL state.
    struct Geometry {
        float width {0};
        float height {0};
        int rotation {0};
        int windowHeight {0};
        int viewportX {0};
        int viewportY {0};
        int viewportWidth {0};
        int viewportHeight {0};
        int drawableWidth {0};
        int drawableHeight {0};
        bool valid() const;
        bool operator==(const Geometry& other) const;
        bool toLogical(Point normalized, Point& logical) const;
        Point toNormalized(Point logical) const;
        Rect visible() const;
    };

    struct Options {
        float size {1};
        float opacity {1};
        int fadeSeconds {6};
        bool tv {false};
        bool invalidSize {false};
        bool invalidOpacity {false};
        bool clampedFade {false};
        static Options parse(std::string_view size,
                             std::string_view opacity,
                             int fadeSeconds,
                             bool tv);
    };

    struct Button {
        int id {NO_BUTTON};
        int cluster {-1};
        Point centre;
        Rect hit;
        float width {0};
        float height {0};
        float rotation {0};
        bool circle {false};
    };

    struct Transition {
        int id {NO_BUTTON};
        int value {0};
    };

    // Input returns at most two entries (release, press). Cancellation returns at
    // most fourteen releases. Both are bounded values, with no deferred event queue.
    struct Transitions {
        std::array<Transition, 14> entries {};
        int count {0};
        void add(int id, int value) { entries[count++] = {id, value}; }
    };

    enum class Event {
        DOWN,
        MOTION,
        UP
    };
    enum class Fade {
        VISIBLE,
        FADING,
        HIDDEN
    };

    class Model
    {
    public:
        Transitions rebuild(const Geometry& geometry, const Options& options, float logicalDpi);
        Transitions cancel();
        Transitions clear();
        Transitions input(Event event, int fingerId, Point normalized, bool legacySingle = false);
        void suppress();
        void wake(bool explicitWake);
        void setFadeSeconds(int seconds);
        void update(int milliseconds);

        const Geometry& geometry() const { return mGeometry; }
        const std::array<Button, 14>& buttons() const { return mButtons; }
        const Rect& safeArea() const { return mSafe; }
        float density() const { return mDensity; }
        float diameter() const { return mDiameter; }
        bool densityFallback() const { return mDensityFallback; }
        bool supported() const { return mSupported; }
        bool compact() const { return mCompact; }
        bool tableFull() const { return mTableFull; }
        int tracked() const;
        int references(int index) const { return mReferences[index]; }
        bool highlighted(int index) const { return mReferences[index] && !mSuppressed[index]; }
        std::uint64_t epoch() const { return mEpoch; }
        Fade fade() const { return mFade; }
        float alpha() const;

    private:
        struct Finger {
            int id {0};
            int cluster {-1};
            int held {-1};
        };
        void layout(float diameter, bool insetPad = false);
        void compactLayout(float diameter);
        bool fits() const;
        int capture(Point p) const;
        int select(int cluster, Point p, int held) const;
        void release(Finger& finger, Transitions& result);
        void hold(Finger& finger, int index, Transitions& result);

        Geometry mGeometry;
        Options mOptions;
        Rect mSafe;
        std::array<Button, 14> mButtons {};
        std::array<Finger, 32> mFingers {};
        std::array<int, 14> mReferences {};
        std::array<bool, 14> mSuppressed {};
        float mDensity {1};
        float mDiameter {0};
        float mIdle {0};
        std::uint64_t mEpoch {0};
        Fade mFade {Fade::VISIBLE};
        bool mDensityFallback {false};
        bool mSupported {false};
        bool mCompact {false};
        bool mTableFull {false};
    };
} // namespace TouchOverlay

#endif // ES_CORE_INPUT_OVERLAY_MODEL_H
