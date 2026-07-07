{{/*
CA Bundle helper templates.
Provides shell functions for combining multiple CA bundle files and helper templates.

Required environment variables:
  CA_BUNDLE_FILE_PATHS  - space-separated list of file paths to include directly
  CA_BUNDLE_MOUNT_PATHS - space-separated list of directories to glob for .crt/.pem files
  CA_BUNDLE_OUTPUT      - path to the combined output file

Functions provided:
  compute_checksum   - compute SHA256 of all source files
  combine_ca_bundles - concatenate sources into output file

Templates provided:
  mlflow.caBundleFilePaths  - extracts filePaths as space-separated string
  mlflow.caBundleMountPaths - extracts mount paths from configMaps as space-separated string
*/}}

{{/*
Extract file paths from caBundle.filePaths as a space-separated string.
Usage: {{ include "mlflow.caBundleFilePaths" . }}
*/}}
{{- define "mlflow.caBundleFilePaths" -}}
{{- .Values.caBundle.filePaths | join " " -}}
{{- end -}}

{{/*
Extract mount paths from caBundle.configMaps as a space-separated string.
Usage: {{ include "mlflow.caBundleMountPaths" . }}
*/}}
{{- define "mlflow.caBundleMountPaths" -}}
{{- $paths := list -}}
{{- range .Values.caBundle.configMaps -}}
{{- $paths = append $paths .mountPath -}}
{{- end -}}
{{- $paths | join " " -}}
{{- end -}}

{{/*
Render CA bundle ConfigMap and combined output volumes.
Usage: {{ include "mlflow.caBundleVolumes" . | nindent 8 }}
*/}}
{{- define "mlflow.caBundleVolumes" -}}
{{- if .Values.caBundle.configMaps }}
{{- range $i, $cm := .Values.caBundle.configMaps }}
- name: ca-bundle-{{ $i }}
  configMap:
    name: {{ $cm.name }}
{{- end }}
- name: combined-ca-bundle
  emptyDir: {}
{{- end }}
{{- end -}}

{{/*
Render the init container that combines CA bundle sources into one file.
Usage: {{ include "mlflow.caBundleInitContainers" . | nindent 6 }}
*/}}
{{- define "mlflow.caBundleInitContainers" -}}
{{- if .Values.caBundle.configMaps }}
initContainers:
  - name: combine-ca-bundles
    image: {{ include "mlflow.image" . }}
    {{- if .Values.image.pullPolicy }}
    imagePullPolicy: {{ .Values.image.pullPolicy }}
    {{- end }}
    command:
      - /bin/sh
      - -c
      - |
        set -e
{{ include "mlflow.caBundleFunctions" . | indent 8 }}
        combine_ca_bundles
    env:
      - name: CA_BUNDLE_FILE_PATHS
        value: {{ include "mlflow.caBundleFilePaths" . | quote }}
      - name: CA_BUNDLE_MOUNT_PATHS
        value: {{ include "mlflow.caBundleMountPaths" . | quote }}
      - name: CA_BUNDLE_OUTPUT
        value: {{ .Values.caBundle.outputPath | quote }}
    volumeMounts:
      - name: tmp
        mountPath: /tmp
      - name: combined-ca-bundle
        mountPath: {{ dir .Values.caBundle.outputPath }}
      {{- range $i, $cm := .Values.caBundle.configMaps }}
      - name: ca-bundle-{{ $i }}
        mountPath: {{ $cm.mountPath }}
        readOnly: true
      {{- end }}
    {{- with .Values.securityContext }}
    securityContext:
      {{- toYaml . | nindent 6 }}
    {{- end }}
    resources:
      requests:
        cpu: 10m
        memory: 16Mi
      limits:
        cpu: 100m
        memory: 64Mi
{{- end }}
{{- end -}}

{{- define "mlflow.caBundleFunctions" -}}
# Compute checksum of CA bundle source files
compute_checksum() {
  (
    # Include file paths (e.g., system CA bundle)
    for f in $CA_BUNDLE_FILE_PATHS; do
      [ -f "$f" ] && cat "$f" 2>/dev/null || true
    done
    # Glob .crt and .pem files from each mount path
    for dir in $CA_BUNDLE_MOUNT_PATHS; do
      for f in "$dir"/*.crt "$dir"/*.pem; do
        [ -f "$f" ] && cat "$f" 2>/dev/null || true
      done
    done
  ) | sha256sum | cut -d' ' -f1
}

# Combine CA bundle files into a single PEM file
combine_ca_bundles() {
  local output="${CA_BUNDLE_OUTPUT}"
  local temp="${output}.tmp"
  local count=0

  umask 0077

  # Initialize temp file
  echo -n "" > "$temp"

  # Include file paths first (e.g., system CA bundle)
  for f in $CA_BUNDLE_FILE_PATHS; do
    if [ -f "$f" ]; then
      cat "$f" >> "$temp"
      echo "" >> "$temp"
      count=$((count + 1))
    fi
  done

  # Glob .crt and .pem files from each mount path
  for dir in $CA_BUNDLE_MOUNT_PATHS; do
    for f in "$dir"/*.crt "$dir"/*.pem; do
      if [ -f "$f" ]; then
        cat "$f" >> "$temp"
        echo "" >> "$temp"
        count=$((count + 1))
      fi
    done
  done

  # Atomically replace the output file
  mv "$temp" "$output"
  chmod 0644 "$output"

  echo "Combined $count CA bundle sources into $output"
  echo "Certificate count: $(grep -c 'BEGIN CERTIFICATE' "$output" || echo 0)"
}
{{- end -}}
