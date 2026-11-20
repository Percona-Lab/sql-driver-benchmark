#!/bin/bash
# Never let the kernel OOM killer pick the database server: a runaway client must die instead.
for u in mysql mariadb-bench; do
  mkdir -p /etc/systemd/system/$u.service.d
  printf "[Service]\nOOMScoreAdjust=-1000\n" > /etc/systemd/system/$u.service.d/oom.conf
done
systemctl daemon-reload
