// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Host-side SDL screenshot label verification.
// Uses only the JDK already required by the Android build and the repository font.
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.font.TextAttribute;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.imageio.ImageIO;

class SmokeMenuFocus {
    static final String[] LABELS = {
        "SEARCH", "SCRAPER", "UI SETTINGS", "SOUND SETTINGS", "INPUT DEVICE SETTINGS",
        "GAME COLLECTION SETTINGS", "OTHER SETTINGS", "UTILITIES", "QUIT ES-DE",
        "GAME IMPORTER", "ORPHANED DATA CLEANUP", "CREATE/UPDATE SYSTEM DIRECTORIES",
        "RESCAN ROM DIRECTORY", "ALTERNATIVE EMULATORS", "EMULATOR MANAGER",
        "AUDIO DRIVER (REQUIRES RESTART)", "NAVIGATION SOUNDS VOLUME",
        "CONTROLLER TYPE", "TOUCH OVERLAY SIZE"
    };

    static int gray(BufferedImage image, int x, int y) {
        int rgb = image.getRGB(x, y);
        int r = (rgb >> 16) & 255, g = (rgb >> 8) & 255, b = rgb & 255;
        return Math.max(r, Math.max(g, b)) - Math.min(r, Math.min(g, b)) <= 3 ? r : -1;
    }

    static BufferedImage trim(BufferedImage image) {
        int left = image.getWidth(), top = image.getHeight(), right = -1, bottom = -1;
        for (int y = 0; y < image.getHeight(); y++) {
            for (int x = 0; x < image.getWidth(); x++) {
                if ((image.getRGB(x, y) & 255) > 64) {
                    left = Math.min(left, x); right = Math.max(right, x);
                    top = Math.min(top, y); bottom = Math.max(bottom, y);
                }
            }
        }
        if (right < left) throw new IllegalArgumentException("Selected band has no readable text");
        return image.getSubimage(left, top, right - left + 1, bottom - top + 1);
    }

    static BufferedImage render(String label, Font font) {
        BufferedImage canvas = new BufferedImage(2400, 300, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = canvas.createGraphics();
        g.setColor(new Color(128, 128, 128));
        // The frontend shapes with HarfBuzz kerning. Java disables it by
        // default; enable it rather than relaxing label-match thresholds.
        g.setFont(font.deriveFont(Map.of(TextAttribute.KERNING, TextAttribute.KERNING_ON)));
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        g.drawString(label, 10, 200);
        g.dispose();
        return trim(canvas);
    }

    static double distance(BufferedImage actual, BufferedImage template) {
        double ratio = (double) actual.getWidth() / actual.getHeight();
        double expected = (double) template.getWidth() / template.getHeight();
        if (Math.abs(ratio / expected - 1) > 0.08) return 1;
        int different = 0, ink = 0;
        // Compare normalized silhouettes; host and Android font rasterizers may
        // differ at antialiased edges. Both word width and strokes must match.
        for (int y = 0; y < 32; y++) {
            for (int x = 0; x < 320; x++) {
                boolean a = (actual.getRGB(x * actual.getWidth() / 320,
                        y * actual.getHeight() / 32) & 255) > 64;
                boolean b = (template.getRGB(x * template.getWidth() / 320,
                        y * template.getHeight() / 32) & 255) > 64;
                if (a || b) ink++;
                if (a != b) different++;
            }
        }
        return (double) different / Math.max(1, ink);
    }

    static BufferedImage labelColumn(BufferedImage band) {
        // Labels use ordinary word spaces; a larger blank gap separates the
        // right-hand slider/value. Match all label ink, never a text prefix.
        int last = -1;
        for (int x = 0; x < band.getWidth(); x++) {
            boolean ink = false;
            for (int y = 0; y < band.getHeight(); y++) {
                if ((band.getRGB(x, y) & 255) > 64) { ink = true; break; }
            }
            if (!ink) continue;
            if (last >= 0 && x - last > band.getHeight() * 0.75) {
                return trim(band.getSubimage(0, 0, last + 1, band.getHeight()));
            }
            last = x;
        }
        return trim(band);
    }

    static String selected(BufferedImage image, Font font) {
        int w = image.getWidth(), h = image.getHeight();
        List<String> matches = new ArrayList<>();
        Set<Integer> bands = new HashSet<>();
        // A settings slider can cross one probe. Require the same complete
        // black selector band and gray neighbours at an unobstructed probe.
        for (int probe : new int[] {w * 7 / 10, w * 6 / 10}) {
            for (int y = 2; y < h - 2; y++) {
                // Default dark menu: the selector is black, bordered by the menu's
                // dark-gray body. Do not infer focus from row position or text alone.
                if (gray(image, probe, y) != 0 || gray(image, probe, y - 1) == 0) continue;
                int end = y;
                while (end < h && gray(image, probe, end) == 0) end++;
                if (end - y < Math.min(w, h) * 0.035 || end - y > Math.min(w, h) * 0.12) continue;
                int above = gray(image, probe, y - 2);
                if (above < 20 || above > 55 || end + 2 >= h) continue;
                int below = gray(image, probe, end + 2);
                if (below < 20 || below > 55) continue;
                if (bands.contains(y)) continue;
                int left = probe, right = probe;
                while (left > 0 && gray(image, left - 1, y - 2) == above) left--;
                while (right + 1 < w && gray(image, right + 1, y - 2) == above) right++;
                if (right - left < w / 3) continue;
                // Exclude the right-hand arrow, retain the complete label.
                BufferedImage word = labelColumn(image.getSubimage(left + 2, y,
                        right - left - Math.max(8, w / 25), end - y));
                String best = "";
                double score = 1, second = 1;
                for (String label : LABELS) {
                    double candidate = distance(word, render(label, font));
                    if (candidate < score) { second = score; score = candidate; best = label; }
                    else second = Math.min(second, candidate);
                }
                System.err.println(best + " score=" + score + " second=" + second);
                if (score > 0.27 || second - score < 0.10) {
                    throw new IllegalArgumentException("Unreadable/ambiguous selected label: best="
                            + best + " distance=" + score + " second=" + second);
                }
                matches.add(best);
                bands.add(y);
                y = end;
            }
        }
        if (matches.size() != 1) throw new IllegalArgumentException("Expected one selected menu band, found " + matches);
        return matches.get(0);
    }

    static BufferedImage fixture(String label, Font font, int w, int h, boolean selected) {
        BufferedImage image = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = image.createGraphics();
        int left = w / 20, width = w * 9 / 10, top = h / 5;
        int row = Math.round(Math.min(w, h) * 0.06f);
        g.setColor(new Color(25, 25, 25));
        g.fillRect(left, top, width, row * 5);
        g.setColor(selected ? Color.BLACK : new Color(25, 25, 25));
        g.fillRect(left, top + row * 2, width, row);
        g.setColor(new Color(128, 128, 128));
        g.setFont(font.deriveFont(Map.of(TextAttribute.KERNING, TextAttribute.KERNING_ON)));
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        g.drawString(label, left + 12, top + row * 3 - row / 4);
        g.dispose();
        return image;
    }

    static void controls(Font base, File directory) throws Exception {
        directory.mkdirs();
        for (int[] size : new int[][] {{540, 960}, {1080, 1920}, {1920, 1080}}) {
            int w = size[0], h = size[1];
            Font font = base.deriveFont(Math.min(w, h) * (h > w ? 0.040f : 0.045f));
            for (String label : LABELS) {
                BufferedImage image = fixture(label, font, w, h, true);
                String found = selected(image, font);
                if (!label.equals(found)) throw new AssertionError(label + " read as " + found);
                if (label.equals("QUIT ES-DE")) ImageIO.write(image, "png", new File(directory, "quit-" + w + ".png"));
                if (label.equals("NAVIGATION SOUNDS VOLUME") || label.startsWith("AUDIO DRIVER")) {
                    // A real settings row has a separate value and can have a
                    // slider crossing the old 70%-width selector probe.
                    Graphics2D g = image.createGraphics();
                    g.setColor(new Color(128, 128, 128));
                    g.setFont(font);
                    int row = Math.round(Math.min(w, h) * 0.06f), top = h / 5;
                    g.drawString("70%", w * 84 / 100, top + row * 3 - row / 4);
                    g.fillRect(w * 68 / 100, top + row * 2 + row / 2, w * 12 / 100, 2);
                    g.dispose();
                    if (!label.equals(selected(image, font))) throw new AssertionError("Value changed label");
                }
            }
            for (String label : new String[] {"UNRECOGNIZED", "GAME IMPORTER EXTRA",
                    "NAVIGATION SOUNDS VOLUME EXTRA", ""}) {
                try {
                    selected(fixture(label, font, w, h, true), font);
                    throw new AssertionError("Unknown selected text escaped: " + label);
                } catch (IllegalArgumentException expected) { }
            }
            try {
                selected(fixture("UTILITIES", font, w, h, false), font);
                throw new AssertionError("Unselected UTILITIES escaped");
            } catch (IllegalArgumentException expected) { }
        }
        System.out.println("PASS: every known label including QUIT recognized at three resolutions; unknown/unselected labels rejected");
    }

    public static void main(String[] args) throws Exception {
        // Match the frontend's HarfBuzz-shaped text, including standard kerning.
        Font font = Font.createFont(Font.TRUETYPE_FONT,
                new File("resources/fonts/Akrobat-SemiBold.ttf"))
                .deriveFont(Map.of(TextAttribute.KERNING, TextAttribute.KERNING_ON));
        if (args[0].equals("--controls")) {
            controls(font, new File(args[1]));
            return;
        }
        BufferedImage image = ImageIO.read(new File(args[0]));
        float size = Math.min(image.getWidth(), image.getHeight())
                * (image.getHeight() > image.getWidth() ? 0.040f : 0.045f);
        System.out.println(selected(image, font.deriveFont(size)));
    }
}
