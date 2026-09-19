# gr_security_base

**Generator Rental ERP — Security base (groups, categories, base menu)**

Part of the **Generator Rental ERP** vertical suite (Odoo 18 Community) for a
KSA generator-rental operation.

- **Module prefix:** `gr_`
- **Depends on:** base,mail
- **Dependency layer position:** 1 of 10
- **Status:** M0 scaffold (structure + dependencies). Business models and views
  are delivered in later milestones per the project plan.

## Install (generator instance only)

```bash
sudo systemctl stop odoo-gen
sudo -u odoo18 /opt/odoo18/venv/bin/python3 /opt/odoo18/odoo/odoo-bin \
  -c /etc/odoo-gen/odoo-gen.conf -d generator -i gr_security_base --stop-after-init
sudo systemctl start odoo-gen
```

> Never target the `pilot` database or the `odoo18` service.
