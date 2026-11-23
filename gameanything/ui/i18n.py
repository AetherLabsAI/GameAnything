"""English for the strings the server builds (statuses, step texts, to-do lines, errors shown in the page).

Key = the Chinese source text (a str.format template when it has {vars}); a list value is [one, many] picked by n.
The page asks with the X-Lang header (or ?lang=); anything not in EN stays Chinese. User and agent content is never passed through here.
"""
import re

LANGS = ("zh", "en")

EN = {
    # rounds / statuses
    "现在没有在进行的版本": "No round in progress",
    "{t} · 进行中": "{t} · in progress",
    "进行中": "In progress", "计划中": "Planned", "方案定了，等你点开工": "Plan ready, waiting for your go", "已定稿": "Final",
    "方案写好了，等你确认": "Plan written, waiting for you to confirm it",
    "{n} 条意见": ["{n} note", "{n} notes"], "等你看录像": "Recording to watch", "做好了": "Built",
    "还没登记": "not registered yet", "完整录像": "Full recording",
    "没有扩展名": "no extension",
    # milestone names (fallbacks when world_plan.yaml has no name)
    "婚礼仪式": "The ceremony", "合影、喜宴、敬酒、捧花": "Photos, banquet, toasts, bouquet", "婚后": "After the wedding",
    "领证那天": "Registration day", "整天改进": "Whole-day polish", "收尾交付": "Wrap-up",
    # 这一天
    "你的意见已交给下一版": "Your notes are with the next round", "你留了意见，还没交给下一版": "You left notes, not handed over yet",
    "检查里还有 {n} 项没做到": ["{n} check still not done", "{n} checks still not done"], "{name}里能玩": "Playable in {name}", "还没做": "Not made yet",
    "确认回忆板里的时刻和顺序": "Confirm the moments and their order", "看 {n} 个新形象（行走图和头像）": ["Look at {n} new look (sprite and portrait)", "Look at {n} new looks (sprites and portraits)"],
    "看{name}的试玩录像": "Watch the {name} playthrough",
    # 素材
    "读取拍摄时间（{n} 份有）": "Read capture times ({n} have one)", "读取拍摄时间（{n} 份有，{k} 份不太可靠）": "Read capture times ({n} have one, {k} not very reliable)",
    "去掉重复的照片（{n} 组，每组留最大的一张）": "Removed duplicate photos ({n} groups, the largest of each kept)",
    "视频抽出关键画面（{n} 段）": "Pulled key frames from videos ({n})", "语音转成文字（{n} 段，本机识别）": "Speech turned into text ({n}, recognised on this computer)",
    "框出照片里的人（{n} 张）": "Boxed the people in photos ({n})",
}
# server errors that reach the page: regex on the Chinese message -> English template
PAT = [(re.compile(p, re.S), e) for p, e in [
    (r"文件名不合法（不能含 \.\. 或以点开头的名字）", "Invalid file name (no .. and no names starting with a dot)"),
    (r"文件名不合法", "Invalid file name"),
    (r"还没有打开的项目", "No project is open yet"), (r"examples 应该是一个列表", "examples should be a list"),
    (r"不支持这种文件（(.*)）：只收 (.*)", "Unsupported file type ({0}): only {1} accepted"),
    (r"上传编号不合法", "Invalid upload id"),
    (r"缺少 Content-Range", "Missing Content-Range"),
    (r"Content-Range 和内容长度对不上", "Content-Range does not match the content length"),
    (r"文件太大（(.*) GB，上限 (.*) GB）", "File too large ({0} GB, limit {1} GB)"),
    (r"这个上传编号已经用于另一个文件", "This upload id is already used by another file"),
    (r"接上的位置不对", "Wrong position to resume from"),
    (r"磁盘空间不够", "Not enough disk space"),
    (r"传输中断，可以接着传", "Transfer interrupted; it can resume"),
    (r"收件箱里还没有文件", "There are no files in the inbox yet"),
    (r"这个页面打开后，文件被别处改过了：请刷新页面再改（刷新前没保存的改动会丢）", "The file changed elsewhere since this page opened: reload and edit again (unsaved changes will be lost)"),
    (r"外观配方在别处被改过了：请刷新页面再改", "The look recipe changed elsewhere: reload and edit again"),
    (r"这个页面打开后，回忆板或你的修改在别处变过了：请刷新页面再改（刷新前没保存的改动会丢）", "The memory board or your edits changed elsewhere since this page opened: reload and edit again (unsaved changes will be lost)"),
    (r"时刻列表和回忆板对不上，请刷新页面", "The moment list does not match the memory board: please reload"),
    (r"(.*): 重要程度或分段不合法", "{0}: invalid importance or segment"),
    (r"方案在别处变过了：请刷新页面再选", "The plan changed elsewhere: reload and choose again"),
    (r"现在没有这一版的方案，请刷新页面", "There is no plan for this round now: please reload"),
    (r"条目 (.*) 不合法", "Item {0} is invalid"),
    (r"留存选项不合法", "Invalid keep option"),
    (r"context 里有不认识的东西", "Unknown item in the context"),
    (r"找不到附件 (.*)", "Attachment {0} not found"),
    (r"说点什么吧", "Say something first"),
    (r"消息太长（(\d+) 个字）：一条最多 (\d+) 个字。长的内容请存成文件，作为附件发", "Message too long ({0} characters): at most {1} per message. Save long text as a file and attach it"),
    (r"找不到这张卡", "Card not found"),
    (r"画面格式不对", "Unsupported frame format"),
    (r"回答应该是一个对象", "The answer should be an object"),
    (r"(.*) 卡不需要回答", "A {0} card needs no answer"),
    (r"构建位置应该是 lab 或 native", "Where to build should be lab or native"),
    (r"开游戏的设置应该是 ask、window、always 或 idle", "When to open the game should be ask, window, always or idle"),
    (r"没在用电脑的分钟数应该是 1 到 720 之间的整数", "The minutes away from the computer should be a whole number from 1 to 720"),
    (r"操作游戏的设置应该是 idle 或 always", "Driving the game should be idle or always"), (r"切到前面的设置应该是 never 或 away", "Bringing the game to the front should be never or away"),
    (r"谁来点游戏应该是 agent 或 self", "Who clicks should be agent or self"), (r"时间段应该像 22:00-08:00", "The time window should look like 22:00-08:00"),
    # gameanything hub: login, roles, access requests
    (r"请先登录", "Please log in first"), (r"用户名或密码不对", "Wrong user name or password"),
    (r"试错太多次了，请过几分钟再试", "Too many tries: wait a few minutes"), (r"请求不对", "Bad request"),
    (r"找不到这个项目", "Project not found"), (r"没有权限", "Not allowed"), (r"没有权限打开这个项目", "You may not open this project"),
    (r"只有项目的所有者能改成员", "Only the project's owner can change members"), (r"只有项目的所有者能删除项目", "Only the project's owner can delete it"),
    (r"只有项目的所有者能决定权限申请", "Only the project's owner can decide access requests"), (r"只有项目的所有者能做这一步", "Only the project's owner can do this"),
    (r"只有管理员能改全局设置", "Only an administrator can change the global settings"),
    (r"这个项目没有共享给你：可以在项目列表里申请权限", "This project is not shared with you: ask for access in the project list"),
    (r"你现在只能看：申请评论或编辑权限后才能在这里说话", "You can only read here: ask for comment or edit access to write"),
    (r"你没有编辑权限：申请编辑权限后才能做这一步", "You have no edit access: ask for edit access to do this"),
    (r"你已经有这个权限了", "You already have this access"), (r"这是你自己的项目", "This is your own project"),
    (r"这个项目还没有所有者", "This project has no owner yet"), (r"角色应该是 view / comment / edit", "The role should be view / comment / edit"),
    (r"没有用户 (.*)", "No user {0}"), (r"所有者不需要加成员", "The owner does not need to be a member"),
    # gameanything hub: 「我的 Claude」, passwords, 「用户管理」
    (r"密码至少 (\d+) 个字符", "The password needs at least {0} characters"), (r"用户 (.*) 已经存在", "User {0} already exists"),
    (r"用户名只能用小写字母、数字、- 和 _，以字母开头，2 到 32 个字符", "A user name uses lower-case letters, digits, - and _, starts with a letter, 2 to 32 characters"),
    (r"原密码不对", "The current password is wrong"), (r"只有管理员能管理用户", "Only an administrator can manage users"),
    (r"不能移除你自己", "You cannot remove yourself"), (r"不能移除最后一个管理员", "The last administrator cannot be removed"),
    (r"至少要留一个管理员", "At least one administrator must stay"),
    (r"连接方式应该是 subscription 或 api_key", "The kind should be subscription or api_key"), (r"请先粘贴", "Paste it first"),
    (r"这是 API key，不是订阅 token：请用下面的「API key」方式", "This is an API key, not a subscription token: use the “API key” option below"),
    (r"这看起来不是 claude setup-token 给的 token（应该以 sk-ant-oat 开头）", "This does not look like a token from claude setup-token (it starts with sk-ant-oat)"),
    (r"这是订阅 token，不是 API key：请用上面的「订阅」方式", "This is a subscription token, not an API key: use the “Subscription” option above"),
    (r"这看起来不是 Anthropic API key（应该以 sk-ant-api 开头）", "This does not look like an Anthropic API key (it starts with sk-ant-api)"),
    (r"格式不对：只应该有字母、数字、- 和 _，请完整复制", "Wrong format: only letters, digits, - and _; copy all of it"),
    (r"还没有连接：先粘贴订阅 token 或 API key", "Not connected yet: paste a subscription token or an API key first"),
    (r"还没有连接：先粘贴 OpenAI API key，或在服务器上 codex login", "Not connected yet: paste an OpenAI API key, or log in with codex login on the server"),
    (r"agent 应该是 claude-code 或 codex", "The agent should be claude-code or codex"),
    (r"agent 应该是 claude-code、codex、opencode 或 gemini", "The agent should be claude-code, codex, opencode or gemini"),
    (r"agent 应该是 claude-code、codex、opencode、gemini 或 dsh", "The agent should be claude-code, codex, opencode, gemini or dsh"),
    (r"还没有连接：先粘贴 DeepSeek 或 OpenRouter 的 API key", "Not connected yet: paste a DeepSeek or OpenRouter API key first"),
    (r"这看起来不是 DeepSeek API key（platform.deepseek.com 的 key 以 sk- 开头）", "This does not look like a DeepSeek API key (keys from platform.deepseek.com start with sk-)"),
    (r"DeepSeek Harness 的模型名不对，例如 deepseek-v4-pro，或用 OpenRouter 时 openrouter/deepseek/deepseek-v4-pro", "Not a model name for DeepSeek Harness, e.g. deepseek-v4-pro, or openrouter/deepseek/deepseek-v4-pro with OpenRouter"),
    (r"只有 OpenCode、Gemini CLI 和 DeepSeek Harness 可以在这里选模型", "Only OpenCode, Gemini CLI and DeepSeek Harness take a model here"),
    (r"还没有连接：先粘贴模型服务的 API key（例如 OpenRouter）", "Not connected yet: paste the API key of your model provider (for example OpenRouter) first"),
    (r"还没有连接：先粘贴 Gemini API key", "Not connected yet: paste a Gemini API key first"),
    (r"这是 Claude 订阅 token，不是 API key：请在 Claude Code 部分保存", "This is a Claude subscription token, not an API key: save it under Claude Code"),
    (r"这看起来不是 (.*)：只应该有字母、数字、-、_ 和 .，请完整复制", "This does not look like a {0}: only letters, digits, -, _ and .; copy all of it"),
    (r"这看起来不是 OpenRouter 的 key（应该以 sk-or- 开头）", "This does not look like an OpenRouter key (it starts with sk-or-)"),
    (r"这看起来不是 Gemini API key（Google AI Studio 的 key 通常以 AIza 开头）", "This does not look like a Gemini API key (Google AI Studio keys usually start with AIza)"),
    (r"模型要写成 provider/model，例如 openrouter/moonshotai/kimi-k2.6", "Write the model as provider/model, e.g. openrouter/moonshotai/kimi-k2.6"),
    (r"Gemini 模型名不对，例如 gemini-3.1-pro-preview", "Not a Gemini model name, e.g. gemini-3.1-pro-preview"),
    (r"只有 OpenCode 和 Gemini CLI 可以在这里选模型", "Only OpenCode and Gemini CLI take a model here"),
    (r"只有项目的所有者能换模型", "Only the project's owner can change the models"),
    (r"应该是 chat 或 build", "Should be chat or build"),
    (r"Claude Code 的模型是 sonnet、opus、haiku、fable（或完整的 claude-… 名字）", "Claude Code models are sonnet, opus, haiku, fable (or a full claude-… name)"),
    (r"Codex 的模型名不对，例如 gpt-6.1-sol", "Not a Codex model name, e.g. gpt-6.1-sol"),
    (r"项目所有者还不能用 (.*)（先在「我的 agent」里登录或填 key）", "The project's owner cannot use {0} yet (log in or add a key in “My agent” first)"),
    (r"「我的 agent」里还没有 (.*) 的 key（(.*)），这个模型跑不起来", "“My agent” has no {0} key yet ({1}), so this model cannot run"),
    (r"没能启动 (opencode|gemini|dsh)：(.*)", "Could not start {0}: {1}"), (r"(opencode|gemini|dsh) 退出码 (.*)", "{0} exited with code {1}"),
    (r"这是 Anthropic（Claude）的 key：请在上面的 Claude 部分保存", "This is an Anthropic (Claude) key: save it under Claude Code"),
    (r"这看起来不是 OpenAI API key（应该以 sk- 开头）", "This does not look like an OpenAI API key (it starts with sk-)"),
    (r"没能建立 Codex 文件夹：(.*)", "Could not create the Codex folder: {0}"), (r"没能启动 codex：(.*)", "Could not start codex: {0}"), (r"codex 退出码 (.*)", "codex exited with code {0}"),
    (r"(\d+) 秒内没有回应", "No answer within {0} s"), (r"没能启动 claude：(.*)", "Could not start claude: {0}"), (r"claude 退出码 (.*)", "claude exited with code {0}"),
    (r"上一次测试还没结束", "The last test has not finished yet"), (r"测试太频繁了，请过 (\d+) 秒再试", "Too many tests: try again in {0} s"),
    # projects, export / import, backup
    (r"项目名不能为空", "Give the project a name"),
    (r"项目类型不合法", "Invalid project type"),
    (r"文件夹已存在：(.*)", "The folder already exists: {0}"),
    (r"找不到这个项目的文件夹", "The folder of this project is gone"),
    (r"正在导出：等它完成", "An export is running: wait for it to finish"),
    (r"正在导入：等它完成", "An import is running: wait for it to finish"),
    (r"找不到上传的文件", "The uploaded file was not found"),
    (r"不是项目文件夹：(.*)", "Not a project folder: {0}"),
    (r"导出文件不能放在项目文件夹里面", "The export file cannot be inside the project folder"),
    (r"不是 GameAnything 导出的文件：(.*)", "Not a GameAnything export file: {0}"),
    (r"导出文件的格式版本（(.*)）比这个工具新：请先升级 GameAnything", "This export file has a newer format ({0}): upgrade GameAnything first"),
    (r"(.*) 已经存在，不会覆盖.*", "{0} already exists and will not be overwritten"),
    (r"上一次导入没有完成：(.*)（确认没人在用后，把它挪走再试）", "A previous import did not finish: {0} (move it away and try again)"),
    (r"文件里有不安全的路径：(.*)", "The file contains an unsafe path: {0}"),
    (r"文件里有不认识的路径：(.*)", "The file contains an unknown path: {0}"),
    (r"导出文件里有符号链接，拒绝导入：(.*)", "The file contains a symbolic link, refusing to import: {0}"),
    (r"清单里没有这个文件：(.*)", "Not in the checksum list: {0}"),
    (r"文件重复：(.*)", "Duplicate file: {0}"),
    (r"校验失败（内容和清单不一致）：(.*)", "Checksum mismatch: {0}"),
    (r"导出文件缺少 (\d+) 个文件，例如 (.*)", "The file is missing {0} file(s), e.g. {1}"),
    (r"要先在对话框里同意", "Agree in the dialog first"),
    (r"备份没有开启.*", "Backup is not turned on"),
    (r"备份正在运行", "A backup is already running"),
    (r"要先选一个备份文件夹", "Pick a backup folder first"),
    (r"备份位置不是文件夹", "The backup location is not a folder"),
    (r"备份文件夹不能在项目文件夹里面，也不能包含项目文件夹", "The backup folder cannot be inside the project folder or contain it"),
    (r"数据集名字应该是 所有者/名字", "The dataset name should look like owner/name"),
    (r"备份目标不合法", "Invalid backup target"),
    (r"找不到原始素材文件夹：(.*)", "Original-material folder not found: {0}"),
    (r"原始素材文件夹重名", "Two original-material folders have the same name"),
    (r"备份位置的空间不够", "Not enough space at the backup location"),
    (r"数据集 (.*) 不是私有的（private）：拒绝备份。先在 Hugging Face 上把它设成私有", "The dataset {0} is not private: backup refused. Make it private on Hugging Face first"),
    (r"没有找到 Hugging Face 的 token：设置环境变量 HF_TOKEN，或运行 gameanything backup token set", "No Hugging Face token found: set HF_TOKEN, or run gameanything backup token set in a terminal"),
    (r"(.*) 的权限太宽：先运行 chmod 600 (.*)", "{0} is readable by others: run chmod 600 {1}"),
]]


def lang_of(headers=None, query=None) -> str:
    v = (query or {}).get("lang", [None])[0] or (headers.get("X-Lang") if headers else None)
    return v if v in LANGS else "zh"


def T(lang, zh, n=None, **kw):
    """The text for `lang`: EN[zh] when English, else zh itself; {vars} filled from kw (and n)."""
    s = EN.get(zh, zh) if lang == "en" else zh
    if isinstance(s, list): s = s[0] if n == 1 else s[1]
    kw = {**kw, **({"n": n} if n is not None else {})}
    return s.format(**kw) if kw else s


def err(msg, lang):
    """Translate a server error message for the page (English only; unknown text is returned as is)."""
    if lang != "en" or not isinstance(msg, str): return msg
    for rx, en in PAT:
        m = rx.fullmatch(msg)
        if m:
            g = [T("en", x) if x == "没有扩展名" else x for x in m.groups()]
            return en.format(*g) if "{" in en else en
    return msg


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def short_date(d, lang) -> str:
    """A date without a year: '10 月 16 日' / 'Oct 16'."""
    return f"{MONTHS[d.month - 1]} {d.day}" if lang == "en" else f"{d.month} 月 {d.day} 日"


_CN_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(s: str):
    """'3' / '三' / '十二' / '二十一' -> int (up to 99); None when it is not a number."""
    s = (s or "").strip()
    if s.isdigit(): return int(s)
    if not s or any(c not in _CN_DIGIT and c != "十" for c in s): return None
    if "十" not in s: return _CN_DIGIT[s] if len(s) == 1 else None
    a, _, b = s.partition("十")
    if "十" in b or len(a) > 1 or len(b) > 1: return None
    return (_CN_DIGIT[a] if a else 1) * 10 + (_CN_DIGIT[b] if b else 0)


def round_name(n: str, lang, tr=lambda s: s, name_en: str = None) -> str:
    """'第 1 期：婚礼仪式' / '第一版：婚礼仪式' -> '第 1 版 · 婚礼仪式' / 'Round 1 · The ceremony'; other names are translated when known
    (built-in, else the project's tr). name_en: the milestone's own English name (world_plan.yaml `name_en`), used as is in English."""
    if lang == "en" and isinstance(name_en, str) and name_en.strip():
        e = re.fullmatch(r"(?i)(round|version|v)\s*(\d+)\s*(?:[:：·\-–]\s*(.*))?", name_en.strip())
        return f"Round {e.group(2)}" + (f" · {e.group(3)}" if e.group(3) else "") if e else name_en.strip()
    m = re.fullmatch(r"第\s*([0-9]+|[〇零一二两三四五六七八九十]+)\s*[期版](?:\s*[：:·]\s*(.*))?", str(n or "").strip())
    num = cn_number(m.group(1)) if m else None
    if num is None: return tr(T(lang, n))
    rest = m.group(2)
    head = f"Round {num}" if lang == "en" else f"第 {num} 版"
    return head + (f" · {tr(T(lang, rest))}" if rest else "")


# an absolute server path in an error text (/root/..., /home/..., C:\\...): only its last part is shown
_ABS_PATH = re.compile(r"(?:(?<![\w/.:])/(?:root|home|srv|opt|tmp|var|mnt|data|private|Users|workspace|usr|etc|proc|media|run|lib)(?:/[^\s'\"<>(),;]*|(?![\w.-]))"
                       r"|\b[A-Za-z]:\\[^\s'\"<>(),;]*)")


def scrub_paths(text: str) -> str:
    """An error text without absolute server paths (the last part of each path stays, so the message still says which file)."""
    def last(m):
        x = m.group(0).rstrip("/\\"); tail = re.split(r"[/\\]", x)[-1]
        return f"…/{tail}" if tail else "…"
    return _ABS_PATH.sub(last, str(text))
