# github-to-forgejo（日本語）

[English](README.md)

GitHub のユーザーまたは組織が持つ**全部の**リポジトリを、Issue・Pull Request・ラベル・マイルストーン・リリース・
Wiki ごと [Forgejo](https://forgejo.org) へ一度に移します。移した先では組織ごとに振り分け、既定ブランチを保護します。

実測: **132 リポジトリを 26 分**（Issue と PR 込み、家のサーバー）。Python 1 ファイル、標準ライブラリだけ。

Forgejo の画面からの移行は 1 件ずつです。このツールは、読んで直して残しておける「振り分け表」1 枚で全部を移します。

## 使い方（5 段階）

```sh
python3 g2f.py plan --github-owner あなたのGitHub名 > map.toml   # 1. 全リポジトリを表の下書きにする
open -e map.toml                                               # 2. 組織に振り分ける（手元のエージェントに頼んでもよい）
python3 g2f.py migrate --map map.toml --dry-run                # 3. 何が起きるかだけ見る（何も書き込まない）
python3 g2f.py migrate --map map.toml                          # 4. 移す
python3 g2f.py protect --map map.toml                          # 5. 既定ブランチを保護する（役割チームも作れる）
```

## 必要なもの

- Python 3.11 以上
- 届く Forgejo と、そこの管理者（または移す先の組織の持ち主）のトークン → 環境変数 `FORGEJO_TOKEN`
- リポジトリを読める GitHub のトークン → 環境変数 `GITHUB_TOKEN`。Fine-grained トークンなら
  「All repositories」で、Contents・Issues・Pull requests・Metadata を読み取りにすれば足ります。

トークンは環境変数からしか読みません。画面にも、ログにも、表にも書き出しません。チャットに貼る必要もありません。

```sh
read -rs GITHUB_TOKEN && export GITHUB_TOKEN     # 貼り付けて Enter（何も表示されません）
read -rs FORGEJO_TOKEN && export FORGEJO_TOKEN
```

## 振り分け表（map.toml）

`plan` は全リポジトリを `unsorted` の下に並べ、公開・非公開、言語、説明をコメントで添えます。名前を組織の下へ移して
ください。

```toml
[forgejo]
url = "https://forgejo.example.com"

[github]
owner = "あなたのGitHub名"

[defaults]
private = true                 # Forgejo では非公開で作る
archive_orgs = ["archive"]     # この組織のリポジトリは読むだけ（アーカイブ）にする

[protect]
users = ["あなたのForgejo名"]   # 既定ブランチへのプッシュとマージはこの人だけ
protected_files = "acceptance/**;.forgejo/workflows/**"   # 任意: 変更を禁じるファイル

[teams.developers]             # 任意: 全組織に役割チームを作る
permission = "write"
members = ["bot-a"]

[orgs]
tools   = ["cli-thing", "dotfiles"]
web     = ["site", "blog"]
archive = ["old-experiment"]
```

GitHub の各リポジトリは、どれか 1 つの組織にだけ入れてください。入れ忘れがあると `migrate` は始める前に止まり、
名前を教えます。この表は、どこに何を移したかの記録にもなります。

### 振り分けを手元のエージェントに任せる

表はただのテキストです。`plan` の出力を、信頼できる手元の AI エージェント（Claude Code など）に、あなたの
プロジェクトの事情と一緒に渡して、振り分け案を出させられます。家の構成や仕事の事情はあなたの機械の外に
出る必要がなく、このツールもそれを知りません。読むのは出来上がった表だけです。エージェント向けの手順は
[AGENTS.md](AGENTS.md) にあります。

## コマンド

| コマンド | すること |
|---|---|
| `plan --github-owner 名前` | トークンで見える全リポジトリ（フォークを除く）を表の下書きとして出す |
| `migrate --map 表` | 組織を作り、各リポジトリをその組織へ直接移し、archive の組織を読むだけにする。移行済みのものは飛ばすので、失敗しても同じコマンドでやり直せる |
| `organize --map 表 --from-owner ユーザー` | 先にユーザーの下へ移したリポジトリを、組織へ移す |
| `protect --map 表` | 既定ブランチを保護し（プッシュとマージは `[protect] users` だけ）、`[teams]` を全組織に作る |

どれも `--dry-run`（何も書き込まない）と `--log ファイル` が使えます。

## 注意

- 大きなリポジトリは Forgejo の既定の時間制限を超えることがあります。時間切れで失敗したら、Forgejo の `app.ini` の
  `[git.timeout] MIGRATE` を上げて（例 3600）、`migrate` をもう一度実行してください。
- フォークから来た PR は、読むだけの履歴として移ります（ブランチがフォーク側にあるため）。
- Dependabot などのボットの PR も移りますが、ボットが動くのは GitHub 側だけです。
- Issue と PR の番号は変わりません。`owner/repo#123` は同じものを指したままです。
- GitHub 側は何も消しません。GitHub を公開用の写しとして残すか、アーカイブするか、PR を閉じるかはお任せします。

## テスト

```sh
python3 -m pytest -q
```

GitHub と Forgejo を模した偽物を相手に動き、トークンが出力やログに漏れないことも確かめます。

## ライセンス

MIT。保守は最小限です（Issue は読みますが、直すとは約束しません）。
