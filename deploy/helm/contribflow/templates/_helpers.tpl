{{- define "contribflow.labels" -}}
app.kubernetes.io/name: contribflow
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{- define "contribflow.dbHost" -}}
{{ .Release.Name }}-postgres
{{- end }}

{{/* Shared hardening for every container (checked by Checkov in CI). */}}
{{- define "contribflow.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities:
  drop: ["ALL"]
{{- end }}
