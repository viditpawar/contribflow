variable "cluster_name" {
  description = "Name of the local kind cluster."
  type        = string
  default     = "contribflow"
}

variable "image_tag" {
  description = "Tag of the locally built contribflow image. A new tag loads the image into kind again and rolls the deployment."
  type        = string
}

# Host ports on 127.0.0.1. Grafana avoids 3000, which a local Grafana install often holds.
variable "api_host_port" {
  type    = number
  default = 8080
}

variable "grafana_host_port" {
  type    = number
  default = 3300
}

variable "prometheus_host_port" {
  type    = number
  default = 9090
}
