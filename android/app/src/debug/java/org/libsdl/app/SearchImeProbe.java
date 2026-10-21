//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchImeProbe.java
//
//  Written for ES-DE-Plus. Calls the actual active SDL input connection in CI.
//

package org.libsdl.app;

public final class SearchImeProbe
{
    private SearchImeProbe() {}

    public static boolean edit(String operation, String text)
    {
        if (SDLActivity.mTextEdit == null || SDLActivity.mTextEdit.ic == null)
            return false;
        switch (operation) {
        case "compose":
            return SDLActivity.mTextEdit.ic.setComposingText(text, 1);
        case "commit":
            return SDLActivity.mTextEdit.ic.commitText(text, 1);
        case "delete":
            return SDLActivity.mTextEdit.ic.deleteSurroundingText(1, 0);
        default:
            return false;
        }
    }
}
