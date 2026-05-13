{{/* vim: set filetype=mustache: */}}

{{/*
Expand the chart name.
*/}}
{{- define "wake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fullname (release + chart name, truncated to 63 chars).
*/}}
{{- define "wake.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Chart label.
*/}}
{{- define "wake.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "wake.labels" -}}
helm.sh/chart: {{ include "wake.chart" . }}
{{ include "wake.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "wake.selectorLabels" -}}
app.kubernetes.io/name: {{ include "wake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Service account name.
*/}}
{{- define "wake.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "wake.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Database URL.
*/}}
{{- define "wake.databaseUrl" -}}
{{- $host := printf "%s-postgres" (include "wake.fullname" .) -}}
{{- printf "postgresql+asyncpg://%s:$(POSTGRES_PASSWORD)@%s:5432/%s" .Values.postgres.user $host .Values.postgres.database -}}
{{- end -}}

{{/*
Redis URL.
*/}}
{{- define "wake.redisUrl" -}}
{{- printf "redis://%s-redis:6379" (include "wake.fullname" .) -}}
{{- end -}}

{{/*
Vault URL.
*/}}
{{- define "wake.vaultUrl" -}}
{{- if .Values.vault.url -}}
{{- .Values.vault.url -}}
{{- else -}}
{{- printf "http://%s-vault:8080" (include "wake.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
agentgateway URL.
*/}}
{{- define "wake.agentgatewayUrl" -}}
{{- printf "http://%s-agentgateway:%d" (include "wake.fullname" .) (int .Values.agentgateway.port) -}}
{{- end -}}
