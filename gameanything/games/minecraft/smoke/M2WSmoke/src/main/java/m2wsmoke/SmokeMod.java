package m2wsmoke;

import net.fabricmc.api.ModInitializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

// GameAnything smoke mod (Fabric): logs on load; SmokeClient shows a chat line in the world.
// Build: gameanything native build --game minecraft --install <this folder> (javac against the game's own files, Minecraft 26.x),
// or with the Fabric example mod's Gradle setup (fabric-example-mod), then install the jar from build/libs (not the -sources jar).
public class SmokeMod implements ModInitializer {
    static final Logger LOG = LoggerFactory.getLogger("m2wsmoke");

    @Override
    public void onInitialize() { LOG.info("[M2W-smoke] loaded"); }
}
