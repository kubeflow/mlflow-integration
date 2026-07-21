{{/*
Expand the name of the chart.
*/}}
{{- define "mlflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncated at 63 chars (DNS naming spec limit).
*/}}
{{- define "mlflow.fullname" -}}
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
Names for component workloads with suffix space reserved for Kubernetes limits.
CronJob names are limited to 52 characters; other DNS labels are limited to 63.
*/}}
{{- define "mlflow.gc.fullname" -}}
{{- printf "%s-gc" (include "mlflow.fullname" . | trunc 49 | trimSuffix "-") -}}
{{- end -}}

{{- define "mlflow.traceArchival.fullname" -}}
{{- printf "%s-trace-archival" (include "mlflow.fullname" . | trunc 37 | trimSuffix "-") -}}
{{- end -}}

{{- define "mlflow.traceArchival.configMapName" -}}
{{- printf "%s-config" (include "mlflow.traceArchival.fullname" .) -}}
{{- end -}}

{{- define "mlflow.migration.fullname" -}}
{{- printf "%s-db-migrate" (include "mlflow.fullname" . | trunc 52 | trimSuffix "-") -}}
{{- end -}}

{{/*
Chart name and version for the chart label.
*/}}
{{- define "mlflow.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "mlflow.labels" -}}
helm.sh/chart: {{ include "mlflow.chart" . }}
{{ include "mlflow.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels for pod matching.
*/}}
{{- define "mlflow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mlflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Selector labels for resources that target MLflow server pods only.
*/}}
{{- define "mlflow.serverSelectorLabels" -}}
{{ include "mlflow.selectorLabels" . }}
app.kubernetes.io/component: server
{{- end }}

{{/*
Resolve the deployment namespace.
*/}}
{{- define "mlflow.namespace" -}}
{{- .Release.Namespace }}
{{- end }}

{{/*
Build the full container image reference.
*/}}
{{- define "mlflow.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/*
Port name based on TLS setting.
*/}}
{{- define "mlflow.portName" -}}
{{- if .Values.tls.enabled }}https{{- else }}http{{- end }}
{{- end }}

{{/*
Probe scheme based on TLS setting.
*/}}
{{- define "mlflow.probeScheme" -}}
{{- if .Values.tls.enabled }}HTTPS{{- else }}HTTP{{- end }}
{{- end }}

{{/*
Full service hostname for in-cluster references.
*/}}
{{- define "mlflow.service.fullhost" -}}
{{- printf "%s.%s.svc.cluster.local" (include "mlflow.fullname" .) (include "mlflow.namespace" .) -}}
{{- end }}

{{/*
Preserve MLflow's safe localhost/private-network defaults, add this release's
Kubernetes Service DNS forms, then append explicitly configured external hosts.
*/}}
{{- define "mlflow.allowedHosts" -}}
{{- $service := include "mlflow.fullname" . -}}
{{- $namespace := include "mlflow.namespace" . -}}
{{- $defaults := list "localhost" "127.0.0.1" "[::1]" "0.0.0.0" "localhost:*" "127.0.0.1:*" "[[]::1]:*" "0.0.0.0:*" "192.168.*" "10.*" "172.16.*" "172.17.*" "172.18.*" "172.19.*" "172.20.*" "172.21.*" "172.22.*" "172.23.*" "172.24.*" "172.25.*" "172.26.*" "172.27.*" "172.28.*" "172.29.*" "172.30.*" "172.31.*" "fc00:*" "fd00:*" -}}
{{- $serviceHosts := list $service (printf "%s:*" $service) (printf "%s.%s" $service $namespace) (printf "%s.%s:*" $service $namespace) (printf "%s.%s.svc" $service $namespace) (printf "%s.%s.svc:*" $service $namespace) (include "mlflow.service.fullhost" .) (printf "%s:*" (include "mlflow.service.fullhost" .)) -}}
{{- concat $defaults $serviceHosts (.Values.mlflow.allowedHosts | default (list)) | uniq | join "," -}}
{{- end -}}
