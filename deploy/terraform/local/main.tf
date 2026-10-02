# Local, zero cost environment (D17): a kind cluster, the monitoring stack and contribflow.

resource "kind_cluster" "this" {
  name           = var.cluster_name
  wait_for_ready = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"

      # NodePorts exposed on localhost only.
      extra_port_mappings {
        container_port = 30080 # contribflow API
        host_port      = var.api_host_port
        listen_address = "127.0.0.1"
      }
      extra_port_mappings {
        container_port = 30300 # Grafana
        host_port      = var.grafana_host_port
        listen_address = "127.0.0.1"
      }
      extra_port_mappings {
        container_port = 30090 # Prometheus
        host_port      = var.prometheus_host_port
        listen_address = "127.0.0.1"
      }
    }
  }
}

provider "helm" {
  # Keep Helm state inside this module, so the operator's own Helm repos and cache
  # cannot break or change a run (D32).
  repository_config_path = "${path.module}/.helm/repositories.yaml"
  repository_cache       = "${path.module}/.helm/cache"

  kubernetes = {
    host                   = kind_cluster.this.endpoint
    client_certificate     = kind_cluster.this.client_certificate
    client_key             = kind_cluster.this.client_key
    cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
  }
}

resource "random_password" "postgres" {
  length  = 24
  special = false # the password is embedded in a connection URL
}

resource "random_password" "grafana" {
  length  = 20
  special = false
}

# kube-prometheus-stack, trimmed for a single node laptop cluster (D18).
resource "helm_release" "monitoring" {
  name             = "monitoring"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  version          = "91.8.2"
  namespace        = "monitoring"
  create_namespace = true
  timeout          = 900

  values = [yamlencode({
    alertmanager = { enabled = false }

    # Control plane components kind does not expose for scraping.
    kubeEtcd              = { enabled = false }
    kubeControllerManager = { enabled = false }
    kubeScheduler         = { enabled = false }
    kubeProxy             = { enabled = false }

    prometheus = {
      service = { type = "NodePort", nodePort = 30090 }
      prometheusSpec = {
        # Pick up ServiceMonitors from every release, not only this one.
        serviceMonitorSelectorNilUsesHelmValues = false
        retention                               = "2d"
        resources = {
          requests = { cpu = "100m", memory = "256Mi" }
          limits   = { memory = "1Gi" }
        }
      }
    }

    grafana = {
      service = { type = "NodePort", nodePort = 30300 }
      # Load dashboards from ConfigMaps in any namespace (the contribflow chart ships one).
      sidecar = { dashboards = { searchNamespace = "ALL" } }
    }
  })]

  set_sensitive = [{
    name  = "grafana.adminPassword"
    value = random_password.grafana.result
  }]
}

# kind nodes cannot see the host's Docker images, so load the image explicitly.
resource "terraform_data" "load_image" {
  triggers_replace = [var.image_tag]

  provisioner "local-exec" {
    command = "kind load docker-image contribflow:${var.image_tag} --name ${kind_cluster.this.name}"
  }
}

resource "helm_release" "contribflow" {
  name             = "contribflow"
  chart            = "${path.module}/../../helm/contribflow"
  namespace        = "contribflow"
  create_namespace = true
  timeout          = 300

  set = [{
    name  = "image.tag"
    value = var.image_tag
  }]

  set_sensitive = [{
    name  = "postgres.password"
    value = random_password.postgres.result
  }]

  # The ServiceMonitor CRD comes from the monitoring stack.
  depends_on = [helm_release.monitoring, terraform_data.load_image]
}
