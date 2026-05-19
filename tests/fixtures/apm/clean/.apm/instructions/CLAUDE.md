# Platform Tools

Use `make deploy ENV=staging` to deploy services to the staging cluster.
Run `make test` before pushing any changes.

## Conventions

- All Kubernetes manifests live in `charts/`
- Environment-specific values use `values-{env}.yaml` naming
- Container images are tagged with the short git SHA: `$(git rev-parse --short HEAD)`
- Deployments use rolling updates with `maxUnavailable: 0`

## Debugging

- Check pod status: `kubectl get pods -n $NAMESPACE`
- View logs: `kubectl logs -f deployment/$APP -n $NAMESPACE`
- Port forward for local testing: `kubectl port-forward svc/$APP 8080:80 -n $NAMESPACE`
