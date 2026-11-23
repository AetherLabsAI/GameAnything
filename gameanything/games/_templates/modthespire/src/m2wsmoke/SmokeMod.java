package m2wsmoke;

import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import org.apache.logging.log4j.LogManager;

// GameAnything smoke mod (ModTheSpire-style loader): logs on load.
@SpireInitializer
public class SmokeMod {
    public static void initialize() { LogManager.getLogger("m2wsmoke").info("[M2W-smoke] loaded"); }
}
