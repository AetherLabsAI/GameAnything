package m2wsmoke;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;

// The visible half of the smoke mod: once the player is in a world, one chat line shows that the mod was loaded (a screenshot proves it).
// Uses Fabric API and the game's own (unobfuscated, Minecraft 26.x) class names.
public class SmokeClient implements ClientModInitializer {
    private boolean shown;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(mc -> {
            if (shown || mc.player == null || mc.player.tickCount < 40) return;
            shown = true;
            mc.player.sendSystemMessage(Component.literal("[M2W-smoke] hello from GameAnything"));
            SmokeMod.LOG.info("[M2W-smoke] chat message shown");
        });
    }
}
