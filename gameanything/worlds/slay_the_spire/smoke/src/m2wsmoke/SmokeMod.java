package m2wsmoke;

import basemod.BaseMod;
import basemod.interfaces.PostDungeonInitializeSubscriber;
import basemod.interfaces.PostRenderSubscriber;
import com.badlogic.gdx.graphics.Color;
import com.badlogic.gdx.graphics.g2d.SpriteBatch;
import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.helpers.FontHelper;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

// The smallest useful mod (the lab's hello mod): proves build -> install -> load -> an effect in the game. Every run starts with 999 gold,
// and one line on every screen (the main menu too) shows in a screenshot that the mod was loaded.
@SpireInitializer
public class SmokeMod implements PostDungeonInitializeSubscriber, PostRenderSubscriber {
    private static final Logger log = LogManager.getLogger("m2wsmoke");

    public static void initialize() {
        BaseMod.subscribe(new SmokeMod());
        log.info("[M2W-smoke] loaded");
    }

    @Override
    public void receivePostDungeonInitialize() {
        AbstractDungeon.player.gold = 999;
        AbstractDungeon.player.displayGold = 999;
        log.info("[M2W-smoke] gold set to 999");
    }

    @Override
    public void receivePostRender(SpriteBatch sb) {
        FontHelper.renderFontCentered(sb, FontHelper.charTitleFont, "[M2W-smoke] hello from GameAnything", Settings.WIDTH / 2.0f,
                Settings.HEIGHT * 0.94f, Color.GOLD);
    }
}
