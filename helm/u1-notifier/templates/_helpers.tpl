{{/*
Expand the name of the chart.
*/}}
{{- define "u1-notifier.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "u1-notifier.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "u1-notifier.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
app.kubernetes.io/name: {{ include "u1-notifier.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Secret name — use existingSecret if provided, otherwise the chart-managed one.
*/}}
{{- define "u1-notifier.secretName" -}}
{{- if .Values.printer.existingSecret }}
{{- .Values.printer.existingSecret }}
{{- else }}
{{- include "u1-notifier.fullname" . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "u1-notifier.selectorLabels" -}}
app.kubernetes.io/name: {{ include "u1-notifier.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
