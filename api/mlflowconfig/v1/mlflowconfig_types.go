/*
Copyright 2025 The Kubeflow Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package v1

import metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

// +kubebuilder:validation:XValidation:rule="!has(self.artifactRootPath) || has(self.artifactRootSecret)",message="artifactRootSecret is required when artifactRootPath is set"
// +kubebuilder:validation:XValidation:rule="!has(self.archiveRootPath) || has(self.archiveRootSecret)",message="archiveRootSecret is required when archiveRootPath is set"
//
// MLflowConfigSpec defines the desired configuration for MLflow workspaces within a namespace.
type MLflowConfigSpec struct {
	// ArtifactRootPath is an optional relative path from the bucket root specified in
	// the ArtifactRootSecret. When provided, this path is appended to the bucket URI
	// from the secret to form the resolved artifact root.
	//
	// Example:
	//   artifactRootSecret: "mlflow-artifact-connection"  # Contains bucket: ds-team-bucket
	//   artifactRootPath: "experiments"
	//   resolved artifact root: s3://ds-team-bucket/experiments
	//
	// +optional
	// +kubebuilder:validation:MaxLength=512
	// +kubebuilder:validation:XValidation:rule="self == '' || !self.startsWith('/')",message="artifactRootPath must be relative"
	// +kubebuilder:validation:XValidation:rule="self == '' || !self.matches(r'(^|.*/)\\.\\.(|/.*)$')",message="artifactRootPath must not contain '..' path segments"
	ArtifactRootPath *string `json:"artifactRootPath,omitempty"`

	// ArtifactRootSecret is the fixed secret contract for namespace-scoped artifact
	// root overrides.
	//
	// The provider currently reads only AWS_S3_BUCKET from this Secret to derive
	// the workspace artifact root. It does not retrieve or inject workspace-scoped
	// credentials into MLflow artifact operations yet.
	//
	// The Secret may still include the usual s3-compatible keys:
	// Example Secret:
	//   apiVersion: v1
	//   kind: Secret
	//   metadata:
	//     name: mlflow-artifact-connection
	//     namespace: ds-team-namespace
	//   data:
	//     AWS_ACCESS_KEY_ID: <base64-encoded>
	//     AWS_SECRET_ACCESS_KEY: <base64-encoded>
	//     AWS_S3_BUCKET: <base64-encoded>
	//     AWS_S3_ENDPOINT: <base64-encoded>
	//     AWS_DEFAULT_REGION: <base64-encoded>  # Optional (default region is not always required, e.g. minio)
	//
	// +optional
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:XValidation:rule="self == 'mlflow-artifact-connection'",message="artifactRootSecret must be 'mlflow-artifact-connection'"
	ArtifactRootSecret *string `json:"artifactRootSecret,omitempty"`

	// ArchiveRootPath is an optional relative path from the bucket root specified in
	// ArchiveRootSecret. When provided, this path is appended to the bucket URI
	// from the secret to form the resolved trace archival root.
	//
	// Example:
	//   archiveRootSecret: "mlflow-archive-secret"  # Contains bucket: ds-team-trace-archive
	//   archiveRootPath: "traces"
	//   resolved trace archival root: s3://ds-team-trace-archive/traces
	//
	// +optional
	// +kubebuilder:validation:MaxLength=512
	// +kubebuilder:validation:XValidation:rule="self == '' || !self.startsWith('/')",message="archiveRootPath must be relative"
	// +kubebuilder:validation:XValidation:rule="self == '' || !self.matches(r'(^|.*/)\\.\\.(|/.*)$')",message="archiveRootPath must not contain '..' path segments"
	ArchiveRootPath *string `json:"archiveRootPath,omitempty"`

	// ArchiveRootSecret is the fixed secret contract for namespace-scoped trace archival
	// location overrides.
	//
	// The provider currently reads only AWS_S3_BUCKET from this Secret to derive
	// the workspace trace archival root. It does not retrieve or inject
	// workspace-scoped credentials into MLflow trace archival operations yet.
	//
	// The Secret may still include the usual s3-compatible keys:
	// Example Secret:
	//   apiVersion: v1
	//   kind: Secret
	//   metadata:
	//     name: mlflow-archive-secret
	//     namespace: ds-team-namespace
	//   data:
	//     AWS_ACCESS_KEY_ID: <base64-encoded>
	//     AWS_SECRET_ACCESS_KEY: <base64-encoded>
	//     AWS_S3_BUCKET: <base64-encoded>
	//     AWS_S3_ENDPOINT: <base64-encoded>
	//     AWS_DEFAULT_REGION: <base64-encoded>  # Optional (default region is not always required, e.g. minio)
	//
	// +optional
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:XValidation:rule="self == 'mlflow-archive-secret'",message="archiveRootSecret must be 'mlflow-archive-secret'"
	ArchiveRootSecret *string `json:"archiveRootSecret,omitempty"`

	// TraceArchivalRetention overrides the workspace-level trace archival retention when
	// MLflow 3.13+ trace archival is enabled on the server.
	//
	// Format: <int><unit>, where unit is one of:
	//   - m: minutes
	//   - h: hours
	//   - d: days
	//
	// Examples: "30d", "12h", "90m"
	//
	// +optional
	// +kubebuilder:validation:MaxLength=32
	// +kubebuilder:validation:Pattern=`^[1-9][0-9]*[mhd]$`
	TraceArchivalRetention *string `json:"traceArchivalRetention,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:resource:scope=Namespaced
// +kubebuilder:validation:XValidation:rule="self.metadata.name == 'mlflow'",message="MLflowConfig resource name must be 'mlflow'"

// MLflowConfig is a namespace-scoped configuration resource that allows
// Kubernetes namespace owners to override the default artifact storage and,
// on MLflow 3.13+, trace archival settings for their namespace.
type MLflowConfig struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	// spec defines the desired MLflow configuration for this namespace.
	// +required
	Spec MLflowConfigSpec `json:"spec"`
}

// +kubebuilder:object:root=true

// MLflowConfigList contains a list of MLflowConfig resources.
type MLflowConfigList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []MLflowConfig `json:"items"`
}

func init() {
	SchemeBuilder.Register(&MLflowConfig{}, &MLflowConfigList{})
}
