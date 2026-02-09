# Git push → deploy

Push в несуществующий репо → создаётся репо, ставится post-receive, post-receive выполняется.

## Настройка (один раз)

1. Скопируй `scripts/server_setup` на сервер.

2. На сервере:
```bash
sudo bash scripts/server_setup/setup_fresh_server.sh
```

3. В `/home/git/.ssh/authorized_keys`:
```
command="/opt/deploy/scripts/git_wrap.sh" ssh-rsa AAAA...твой_ключ
```

## Push

```bash
git remote add origin git@СЕРВЕР:sites/PAGE_HASH.git
git push -u origin main
```

Репо создаётся, post-receive ставится и сразу выполняется (checkout → docker build → nginx).

## Удаление сайта

```bash
sudo /opt/deploy/scripts/remove_site.sh PAGE_HASH
```

По умолчанию удаляется и bare git репо — при следующем push git_wrap создаст его заново. Флаг `--keep-repo` оставляет репо.
