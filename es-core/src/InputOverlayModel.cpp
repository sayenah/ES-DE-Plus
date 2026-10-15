//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  InputOverlayModel.cpp
//
//  Written for ES-DE-Plus from the open input contract and MIT overlay assets.
//

#include "InputOverlayModel.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace TouchOverlay
{
    namespace
    {
        constexpr float PI {3.14159265358979323846f};
        float distance(Point a, Point b) { return std::hypot(a.x - b.x, a.y - b.y); }
        Point inverse(const Geometry& g, float u, float v)
        {
            switch (g.rotation) {
                case 90:
                    return {v * g.width, (1 - u) * g.height};
                case 180:
                    return {(1 - u) * g.width, (1 - v) * g.height};
                case 270:
                    return {(1 - v) * g.width, u * g.height};
                default:
                    return {u * g.width, v * g.height};
            }
        }
    } // namespace

    bool Rect::contains(Point p, float expansion) const
    {
        const float left {x - w * (expansion - 1) / 2};
        const float top {y - h * (expansion - 1) / 2};
        // Half-open rectangles give shared compact-grid edges one unambiguous owner.
        return p.x >= left && p.x < left + w * expansion && p.y >= top && p.y < top + h * expansion;
    }

    bool Geometry::valid() const
    {
        return std::isfinite(width) && std::isfinite(height) && width > 0 && height > 0 &&
               windowHeight > 0 && viewportWidth > 0 && viewportHeight > 0 && drawableWidth > 0 &&
               drawableHeight > 0 &&
               (rotation == 0 || rotation == 90 || rotation == 180 || rotation == 270);
    }

    bool Geometry::operator==(const Geometry& o) const
    {
        return width == o.width && height == o.height && rotation == o.rotation &&
               windowHeight == o.windowHeight && viewportX == o.viewportX &&
               viewportY == o.viewportY && viewportWidth == o.viewportWidth &&
               viewportHeight == o.viewportHeight && drawableWidth == o.drawableWidth &&
               drawableHeight == o.drawableHeight;
    }

    bool Geometry::toLogical(Point p, Point& logical) const
    {
        if (!valid() || !std::isfinite(p.x) || !std::isfinite(p.y))
            return false;
        const float top {static_cast<float>(drawableHeight - windowHeight + viewportY)};
        const float u {(std::clamp(p.x, 0.0f, 1.0f) * drawableWidth - viewportX) / viewportWidth};
        const float v {(std::clamp(p.y, 0.0f, 1.0f) * drawableHeight - top) / viewportHeight};
        if (u < 0 || u > 1 || v < 0 || v > 1)
            return false;
        logical = inverse(*this, u, v);
        return true;
    }

    Point Geometry::toNormalized(Point p) const
    {
        if (!valid())
            return {};
        float u {p.x / width};
        float v {p.y / height};
        switch (rotation) {
            case 90:
                u = 1 - p.y / height;
                v = p.x / width;
                break;
            case 180:
                u = 1 - p.x / width;
                v = 1 - p.y / height;
                break;
            case 270:
                u = p.y / height;
                v = 1 - p.x / width;
                break;
            default:
                break;
        }
        return {(viewportX + u * viewportWidth) / drawableWidth,
                (drawableHeight - windowHeight + viewportY + v * viewportHeight) / drawableHeight};
    }

    Rect Geometry::visible() const
    {
        if (!valid())
            return {};
        const float top {static_cast<float>(drawableHeight - windowHeight + viewportY)};
        const Point a {std::clamp(-static_cast<float>(viewportX) / viewportWidth, 0.0f, 1.0f),
                       std::clamp(-top / viewportHeight, 0.0f, 1.0f)};
        const Point b {
            std::clamp(static_cast<float>(drawableWidth - viewportX) / viewportWidth, 0.0f, 1.0f),
            std::clamp((drawableHeight - top) / viewportHeight, 0.0f, 1.0f)};
        if (b.x <= a.x || b.y <= a.y)
            return {};
        // Intersect in viewport coordinates directly: a normalized round trip can
        // round an exact clipped edge just outside the image.
        const Point l {inverse(*this, a.x, a.y)};
        const Point r {inverse(*this, b.x, b.y)};
        return {std::min(l.x, r.x), std::min(l.y, r.y), std::abs(r.x - l.x), std::abs(r.y - l.y)};
    }

    Options Options::parse(std::string_view size, std::string_view opacity, int seconds, bool tv)
    {
        Options o;
        if (size == "x-small")
            o.size = 0.70f;
        else if (size == "small")
            o.size = 0.85f;
        else if (size == "large")
            o.size = 1.20f;
        else
            o.invalidSize = size != "medium";
        if (opacity == "low")
            o.opacity = 0.60f;
        else if (opacity == "verylow")
            o.opacity = 0.35f;
        else
            o.invalidOpacity = opacity != "normal";
        o.fadeSeconds = std::clamp(seconds, 0, 20);
        o.clampedFade = seconds != o.fadeSeconds;
        o.tv = tv;
        return o;
    }

    Transitions Model::rebuild(const Geometry& geometry, const Options& options, float dpi)
    {
        Transitions result {cancel()};
        mGeometry = geometry;
        mOptions = options;
        mSupported = false;
        mCompact = false;
        mTableFull = false;
        const Rect v {geometry.visible()};
        const float shorter {std::min(v.w, v.h)};
        mDensityFallback = !std::isfinite(dpi) || dpi <= 0;
        mDensity = mDensityFallback ? shorter / 411.0f : dpi / 160.0f;
        if (!geometry.valid() || !std::isfinite(mDensity) || mDensity <= 0)
            return result;
        // Conservative margins only: these are NOT Android window insets. Supported
        // normal/compact layouts require at least 288 dp on both visible dimensions.
        if (v.w < 288 * mDensity || v.h < 288 * mDensity)
            return result;
        const bool landscape {v.w >= v.h};
        const float side {
            std::max((landscape ? 32.0f : 24.0f) * mDensity, (landscape ? 0.03f : 0.04f) * v.w)};
        const float top {std::max(24 * mDensity, 0.04f * v.h)};
        const float helpBand {(geometry.width > geometry.height ? 0.064f : 0.04f) *
                              geometry.height};
        const float bottom {std::max(32 * mDensity, helpBand)};
        mSafe = {v.x + side, v.y + top, v.w - 2 * side, v.h - top - bottom};
        const float requested {std::clamp(0.12f * shorter, 56 * mDensity, 84 * mDensity) *
                               options.size};
        // Find a size-independent normal-layout ceiling, preserving monotonic sizes.
        float limit {84 * 1.2f * mDensity};
        for (int i {0}; i < 80; ++i) {
            layout(limit);
            if (fits())
                break;
            limit *= 0.97f;
        }
        if (limit >= 39.2f * mDensity) {
            layout(std::min(requested, limit));
            mSupported = fits();
        }
        if (!mSupported) {
            mCompact = true;
            compactLayout(requested);
            mSupported = fits();
        }
        if (!mSupported)
            mButtons = {};
        wake(false);
        return result;
    }

    void Model::layout(float d)
    {
        mDiameter = d;
        const float hit {std::max(1.15f * d, 48 * mDensity)};
        const float radius {1.05f * d + hit / 2}; // Full 1.625D face extent, not 1.45D.
        const float gap {0.15f * d};
        const float pillH {std::max(0.66f * d * 1.15f, 48 * mDensity)};
        const float shoulderH {std::max(0.5f * d * 1.15f, 48 * mDensity)};
        const float shoulderW {std::max(1.3f * d * 1.15f, 48 * mDensity)};
        const float left {mSafe.x + 1.15f * radius};
        const float right {mSafe.x + mSafe.w - 1.15f * radius};
        const auto visible {mGeometry.visible()};
        const bool landscape {visible.w >= visible.h};
        const float bottomY {mSafe.y + mSafe.h - 1.15f * radius};
        const float y {landscape && std::min(visible.w, visible.h) >= 600 * mDensity ?
                           std::min(bottomY, visible.y + 0.62f * visible.h) :
                           bottomY};
        const std::array<Point, 4> directions {{{0, -1}, {0, 1}, {-1, 0}, {1, 0}}};
        for (int i {0}; i < 14; ++i) {
            Button& b {mButtons[i]};
            b = {};
            b.id = IDS[i];
            b.cluster = i < 4 ? 0 : i < 8 ? 1 : i - 6;
            b.circle = i < 8;
            b.width = i < 8 ? d : i < 10 ? 0.9f * d : 1.3f * d;
            b.height = i < 4 ? d * 40 / 52 : i < 8 ? d : i < 10 ? 0.66f * d : 0.5f * d;
            if (i < 4) {
                b.centre = {left + directions[i].x * 1.05f * d, y + directions[i].y * 1.05f * d};
                b.rotation = i == 0 ? -90 : i == 1 ? 90 : i == 2 ? 180 : 0;
            }
            else if (i < 8) {
                const std::array<Point, 4> face {{{0, 1}, {1, 0}, {-1, 0}, {0, -1}}};
                b.centre = {right + face[i - 4].x * 1.05f * d, y + face[i - 4].y * 1.05f * d};
            }
            else if (i < 10) {
                const float w {std::max(0.9f * d * 1.15f, 48 * mDensity)};
                b.centre = {landscape ? (i == 8 ? left + 1.5f * d : right - 1.5f * d) :
                                        mSafe.x + mSafe.w / 2 + (i == 8 ? -1 : 1) * (w + gap) / 2,
                            y - 1.15f * radius - gap - pillH / 2};
            }
            else {
                const float rowY {y - 1.15f * radius - 2 * gap - pillH - shoulderH / 2};
                // LT, LB ... RB, RT; all rows are V-local and include V's origin.
                const int column {i == 12 ? 0 : i == 10 ? 1 : i == 11 ? 2 : 3};
                b.centre =
                    landscape ?
                        Point {i == 10 || i == 12 ? left - 0.1f * d : right + 0.1f * d,
                               y - 1.15f * radius - gap - shoulderH / 2 -
                                   (i >= 12 ? shoulderH + gap : 0)} :
                        Point {column < 2 ? mSafe.x + shoulderW / 2 + column * (shoulderW + gap) :
                                            mSafe.x + mSafe.w - shoulderW / 2 -
                                                (3 - column) * (shoulderW + gap),
                               rowY};
            }
            const float w {i < 8 ? hit : std::max(b.width * 1.15f, 48 * mDensity)};
            const float h {i < 8 ? hit : std::max(b.height * 1.15f, 48 * mDensity)};
            b.hit = {b.centre.x - w / 2, b.centre.y - h / 2, w, h};
        }
    }

    void Model::compactLayout(float requested)
    {
        const float cell {48 * mDensity};
        const int columns {std::min(7, static_cast<int>(mSafe.w / cell))};
        if (columns < 1)
            return;
        const int rows {(14 + columns - 1) / columns};
        const float spacing {std::min(mSafe.w / columns, mSafe.h / rows)};
        mDiameter = std::min(requested, spacing / 1.5f);
        for (int i {0}; i < 14; ++i) {
            Button& b {mButtons[i]};
            b = {};
            b.id = IDS[i];
            b.cluster = i; // Compact buttons are independent pills; no ambiguous sectors.
            b.centre = {mSafe.x + (i % columns + 0.5f) * spacing,
                        mSafe.y + mSafe.h - (rows - i / columns - 0.5f) * spacing};
            b.width = mDiameter;
            b.height = i < 4  ? mDiameter * 40 / 52 :
                       i < 8  ? mDiameter :
                       i < 10 ? mDiameter * 38 / 52 :
                                mDiameter * 30 / 78;
            b.rotation = i == 0 ? -90 : i == 1 ? 90 : i == 2 ? 180 : 0;
            b.hit = {b.centre.x - cell / 2, b.centre.y - cell / 2, cell, cell};
        }
    }

    bool Model::fits() const
    {
        constexpr float epsilon {0.01f};
        if (mSafe.w <= 0 || mSafe.h <= 0)
            return false;
        for (int i {0}; i < 14; ++i) {
            const Button& b {mButtons[i]};
            if (!std::isfinite(b.hit.x) || !std::isfinite(b.hit.y) ||
                b.hit.w + epsilon < 48 * mDensity || b.hit.h + epsilon < 48 * mDensity ||
                b.hit.x + epsilon < mSafe.x || b.hit.y + epsilon < mSafe.y ||
                b.hit.x + b.hit.w > mSafe.x + mSafe.w + epsilon ||
                b.hit.y + b.hit.h > mSafe.y + mSafe.h + epsilon)
                return false;
            for (int j {0}; j < i; ++j) {
                const Button& a {mButtons[j]};
                if (a.circle && b.circle) {
                    if (distance(a.centre, b.centre) + epsilon < (a.hit.w + b.hit.w) / 2)
                        return false;
                }
                else if (a.hit.x + a.hit.w > b.hit.x + epsilon &&
                         b.hit.x + b.hit.w > a.hit.x + epsilon &&
                         a.hit.y + a.hit.h > b.hit.y + epsilon &&
                         b.hit.y + b.hit.h > a.hit.y + epsilon)
                    return false;
            }
        }
        // Sector capture regions, not just the arm circles, must remain disjoint.
        if (!mCompact) {
            const float r {1.05f * mDiameter + mButtons[0].hit.w / 2};
            if (mButtons[4].centre.x - mButtons[0].centre.x < 2.3f * r + 0.15f * mDiameter)
                return false;
        }
        return true;
    }

    int Model::capture(Point p) const
    {
        if (!mSafe.contains(p))
            return -1;
        if (!mCompact) {
            const float radius {1.05f * mDiameter + mButtons[0].hit.w / 2};
            const Point pad {mButtons[0].centre.x, mButtons[2].centre.y};
            const Point face {mButtons[4].centre.x, mButtons[5].centre.y};
            if (distance(p, pad) <= radius)
                return 0;
            if (distance(p, face) <= radius * 1.15f)
                return 1;
        }
        for (int i {mCompact ? 0 : 8}; i < 14; ++i)
            if (mButtons[i].hit.contains(p))
                return mButtons[i].cluster;
        return -1;
    }

    int Model::select(int cluster, Point p, int held) const
    {
        if (cluster < 0 || !mSafe.contains(p))
            return -1;
        if (mCompact || cluster >= 2) {
            const int i {mCompact ? cluster : cluster + 6};
            return mButtons[i].hit.contains(p, held == i ? 1.15f : 1.0f) ? i : -1;
        }
        const float radius {1.05f * mDiameter + mButtons[0].hit.w / 2};
        if (cluster == 0) {
            const Point pad {mButtons[0].centre.x, mButtons[2].centre.y};
            const float d {distance(p, pad)};
            if (d > radius * (held >= 0 ? 1.4f : 1.0f))
                return -1;
            if (d <= 0.25f * radius)
                return held;
            const float angle {std::atan2(p.y - pad.y, p.x - pad.x)};
            if (held >= 0) {
                const std::array<float, 4> angles {-PI / 2, PI / 2, PI, 0};
                if (std::abs(std::remainder(angle - angles[held], 2 * PI)) <= PI / 4 + PI / 18)
                    return held;
            }
            if (std::abs(p.x - pad.x) >= std::abs(p.y - pad.y))
                return p.x >= pad.x ? 3 : 2;
            return p.y >= pad.y ? 1 : 0;
        }
        const Point face {mButtons[4].centre.x, mButtons[5].centre.y};
        if (distance(p, face) > radius * 1.15f)
            return -1;
        int best {4};
        for (int i {5}; i < 8; ++i)
            if (distance(p, mButtons[i].centre) < distance(p, mButtons[best].centre))
                best = i;
        if (held >= 4 && distance(p, mButtons[held].centre) <=
                             distance(p, mButtons[best].centre) + 0.15f * mDiameter)
            return held;
        return best;
    }

    void Model::release(Finger& f, Transitions& result)
    {
        if (f.held < 0)
            return;
        if (--mReferences[f.held] == 0) {
            result.add(IDS[f.held], 0);
            mSuppressed[f.held] = false;
        }
        f.held = -1;
    }

    void Model::hold(Finger& f, int index, Transitions& result)
    {
        if (index < 0)
            return;
        f.held = index;
        if (mReferences[index]++ == 0)
            result.add(IDS[index], 1);
    }

    Transitions Model::input(Event event, int id, Point normalized, bool legacySingle)
    {
        Transitions result;
        if (!mSupported || id < 1)
            return result;
        Finger* finger {nullptr};
        for (auto& f : mFingers)
            if (f.id == id) {
                finger = &f;
                break;
            }
        if (event == Event::DOWN) {
            const bool hidden {mFade == Fade::HIDDEN};
            wake(true);
            // Fault recovery consumes the duplicate gesture, releases any stale hold,
            // and never treats a missed UP as a second press.
            if (finger) {
                if (legacySingle)
                    return result;
                release(*finger, result);
                finger->cluster = -1;
                return result;
            }
            for (auto& f : mFingers)
                if (f.id == 0) {
                    finger = &f;
                    break;
                }
            if (!finger) {
                mTableFull = true;
                return result;
            }
            *finger = {id, -1, -1};
            Point p;
            if (hidden || !mGeometry.toLogical(normalized, p))
                return result;
            finger->cluster = capture(p);
            hold(*finger, select(finger->cluster, p, -1), result);
        }
        else if (finger && event == Event::UP) {
            release(*finger, result);
            *finger = {};
        }
        else if (finger && finger->cluster >= 0) {
            Point p;
            const int desired {
                mGeometry.toLogical(normalized, p) ? select(finger->cluster, p, finger->held) : -1};
            if (desired != finger->held) {
                release(*finger, result);
                if (legacySingle && result.count)
                    return result;
                hold(*finger, desired, result);
            }
        }
        return result;
    }

    Transitions Model::cancel()
    {
        Transitions result;
        for (int i {0}; i < 14; ++i)
            if (mReferences[i])
                result.add(IDS[i], 0);
        mFingers = {};
        mReferences = {};
        mSuppressed = {};
        mIdle = 0;
        ++mEpoch;
        return result;
    }

    Transitions Model::clear()
    {
        Transitions result {cancel()};
        mSupported = false;
        mButtons = {};
        return result;
    }

    void Model::suppress()
    {
        for (int i {0}; i < 14; ++i)
            if (mReferences[i])
                mSuppressed[i] = true;
    }

    int Model::tracked() const
    {
        int count {0};
        for (const auto& f : mFingers)
            if (f.id)
                ++count;
        return count;
    }

    void Model::wake(bool explicitWake)
    {
        mIdle = 0;
        mFade =
            mOptions.tv && mOptions.fadeSeconds > 0 && !explicitWake ? Fade::HIDDEN : Fade::VISIBLE;
    }

    void Model::setFadeSeconds(int seconds) { mOptions.fadeSeconds = std::clamp(seconds, 0, 20); }

    void Model::update(int milliseconds)
    {
        if (milliseconds < 0 || milliseconds >= 1000 || tracked() || mOptions.fadeSeconds == 0)
            return;
        mIdle += milliseconds;
        const float start {mOptions.fadeSeconds * 1000.0f};
        mFade = mIdle >= start + 500 ? Fade::HIDDEN : mIdle >= start ? Fade::FADING : Fade::VISIBLE;
    }

    float Model::alpha() const
    {
        return mOptions.opacity *
               (mFade == Fade::HIDDEN  ? 0 :
                mFade == Fade::VISIBLE ? 1 :
                                         std::clamp(1 - (mIdle - mOptions.fadeSeconds * 1000) / 500,
                                                    0.0f, 1.0f));
    }
} // namespace TouchOverlay
