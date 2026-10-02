output "api_url" {
  value = "http://localhost:${var.api_host_port}"
}

output "grafana_url" {
  value = "http://localhost:${var.grafana_host_port}/d/contribflow"
}

output "prometheus_url" {
  value = "http://localhost:${var.prometheus_host_port}"
}

output "grafana_admin_password" {
  value     = random_password.grafana.result
  sensitive = true
}
