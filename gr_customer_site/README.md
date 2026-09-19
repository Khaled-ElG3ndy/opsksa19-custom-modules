# gr_customer_site

**Generator Rental ERP — Customer sites**

Part of the **Generator Rental ERP** vertical suite (Odoo 18 Community) for a
KSA generator-rental operation.

- **Module prefix:** `gr_`
- **Depends on:** gr_security_base,gr_fleet_base,mail,contacts
- **Dependency layer position:** 3 of 10
- **Status:** M0 scaffold (structure + dependencies). Business models and views
  are delivered in later milestones per the project plan.

## Install (generator instance only)

```bash
sudo systemctl stop odoo-gen
sudo -u odoo18 /opt/odoo18/venv/bin/python3 /opt/odoo18/odoo/odoo-bin \
  -c /etc/odoo-gen/odoo-gen.conf -d generator -i gr_customer_site --stop-after-init
sudo systemctl start odoo-gen
```

> Never target the `pilot` database or the `odoo18` service.
