# Kubernetes

The fork does not yet publish a namespaced Helm chart or container image. Build
and push the source image to a registry you control, then install the chart from
this checkout with that image override:

```bash
helm install codex-lb ./deploy/helm/codex-lb \
  --set image.registry=registry.example.com \
  --set image.repository=your-org/claudex-lb \
  --set image.tag=your-tag \
  --set postgresql.auth.password=changeme \
  --set config.databaseMigrateOnStartup=true \
  --set migration.schemaGate.enabled=false
kubectl port-forward svc/codex-lb 2455:2455
```

Open [localhost:2455](http://localhost:2455) → Add account → Done.

## Multi-replica behavior

The Helm chart auto-configures HTTP `/responses` owner handoff for multi-replica installs using a headless-service DNS name per pod. The default cluster domain is `cluster.local`; set Helm `clusterDomain` if your cluster uses a different suffix. Override `config.sessionBridgeAdvertiseBaseUrl` only if pods must be reached through a different internal address.

In multi-replica setups, replicas must share the same encryption key (the Helm chart default) for bootstrap-token restart recovery and encrypted-data access to work.

## Full chart reference

For external database, production config, ingress, observability, and more see the
[Helm chart README](https://github.com/joschi655/claudex-lb/blob/main/deploy/helm/codex-lb/README.md).

---

*Specs: [deployment-installation](https://github.com/joschi655/claudex-lb/tree/main/openspec/specs/deployment-installation) · [replica-operations](https://github.com/joschi655/claudex-lb/tree/main/openspec/specs/replica-operations)*
