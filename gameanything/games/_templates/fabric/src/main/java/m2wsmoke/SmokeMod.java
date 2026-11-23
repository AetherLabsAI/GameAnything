package m2wsmoke;

import net.fabricmc.api.ModInitializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

// GameAnything smoke mod (Fabric): logs on load. Build it with the Fabric example mod's Gradle setup (fabric-example-mod), then
// `m2w native install` the jar from build/libs (not the -sources jar).
public class SmokeMod implements ModInitializer {
    private static final Logger LOG = LoggerFactory.getLogger("m2wsmoke");

    @Override
    public void onInitialize() { LOG.info("[M2W-smoke] loaded"); }
}
