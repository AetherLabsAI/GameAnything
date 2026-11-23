# Step perceive — 看图 (you, then her)
Entry: ingested, with photos. No photos: this step is skipped by itself.
Do:
1. One `permission` card in this run (key `perceive`): what is sent (photos reduced to 1024 px, transcripts, document pages), what is not (originals, video files), to whom.
```yaml
kind: permission
key: perceive
title: 让模型看你的照片，写出每张的内容
will_send: [缩小到 1024 像素的照片, 两段致辞的转写文字]
will_not_send: [原图, 视频文件]
to: 你的 Claude Code 会话
en: {title: "Let the model look at your photos and describe each one"}
```
2. When she said yes: `gameanything perceive --project "$P" --emit`, write each request's card yourself, then `gameanything perceive --project "$P" --collect`. Log it in privacy_ledger.yaml.
Exit: she said yes and 2_perceive/cards/ has the cards (she said no: skipped; work from her words only).
Mistakes: looking at photos before the yes; describing people with guesses about who they are (names come from her in the next step).
