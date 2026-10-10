{{/*
Expand the name of the chart.
*/}}
{{- define "urumi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "urumi.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "urumi.labels" -}}
helm.sh/chart: {{ include "urumi.chart" . }}
{{ include "urumi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "urumi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "urumi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "urumi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "urumi.storageClass" -}}
{{- if .Values.global.storageClass }}
{{- .Values.global.storageClass }}
{{- else if .storageClass }}
{{- .storageClass }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{/*
  urumi.secretKey (list <secretFromLookup> <key>)
  Plaintext value of a key in a Secret found via `lookup`, or "" when the Secret/key is
  absent. `lookup` returns base64-encoded data, so callers must decode to compare or reuse
  an existing credential across Secrets (e.g. the MariaDB user password shared by
  mariadb-secret and wordpress-secret).
*/}}
{{- define "urumi.secretKey" -}}
{{- $secret := index . 0 -}}
{{- $key := index . 1 -}}
{{- if $secret -}}
{{- $data := $secret.data | default dict -}}
{{- $raw := index $data $key -}}
{{- if $raw -}}
{{- b64dec $raw -}}
{{- end -}}
{{- end -}}
{{- end }}

