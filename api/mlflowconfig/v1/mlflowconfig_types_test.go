package v1

import (
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
)

func TestAddToSchemeRegistersMLflowConfig(t *testing.T) {
	scheme := runtime.NewScheme()

	if err := AddToScheme(scheme); err != nil {
		t.Fatalf("AddToScheme() error = %v", err)
	}

	kinds, _, err := scheme.ObjectKinds(&MLflowConfig{})
	if err != nil {
		t.Fatalf("ObjectKinds() error = %v", err)
	}

	expected := GroupVersion.WithKind("MLflowConfig")
	for _, kind := range kinds {
		if kind == expected {
			return
		}
	}

	t.Fatalf("expected %v to be registered, got %v", expected, kinds)
}

func TestMLflowConfigDeepCopyCreatesDistinctNestedValues(t *testing.T) {
	artifactRootSecret := "mlflow-artifact-connection"
	artifactRootPath := "experiments"
	archiveRootPath := "traces"
	archiveRootSecret := "mlflow-archive-secret"
	traceArchivalRetention := "14d"
	original := &MLflowConfig{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "mlflow",
			Namespace: "team-a",
		},
		Spec: MLflowConfigSpec{
			ArtifactRootSecret:     &artifactRootSecret,
			ArtifactRootPath:       &artifactRootPath,
			ArchiveRootSecret:      &archiveRootSecret,
			ArchiveRootPath:        &archiveRootPath,
			TraceArchivalRetention: &traceArchivalRetention,
		},
	}

	clone := original.DeepCopy()
	if clone == nil {
		t.Fatal("DeepCopy() returned nil")
	}

	if clone == original {
		t.Fatal("DeepCopy() returned the original pointer")
	}

	if clone.Spec.ArtifactRootSecret == original.Spec.ArtifactRootSecret {
		t.Fatal("DeepCopy() reused the nested artifactRootSecret pointer")
	}

	if clone.Spec.ArtifactRootPath == original.Spec.ArtifactRootPath {
		t.Fatal("DeepCopy() reused the nested artifactRootPath pointer")
	}

	if clone.Spec.ArchiveRootSecret == original.Spec.ArchiveRootSecret {
		t.Fatal("DeepCopy() reused the nested archiveRootSecret pointer")
	}

	if clone.Spec.ArchiveRootPath == original.Spec.ArchiveRootPath {
		t.Fatal("DeepCopy() reused the nested archiveRootPath pointer")
	}

	if clone.Spec.TraceArchivalRetention == original.Spec.TraceArchivalRetention {
		t.Fatal("DeepCopy() reused the nested traceArchivalRetention pointer")
	}

	if *clone.Spec.ArtifactRootSecret != *original.Spec.ArtifactRootSecret {
		t.Fatalf(
			"DeepCopy() changed artifactRootSecret: got %q want %q",
			*clone.Spec.ArtifactRootSecret,
			*original.Spec.ArtifactRootSecret,
		)
	}

	if *clone.Spec.ArtifactRootPath != *original.Spec.ArtifactRootPath {
		t.Fatalf(
			"DeepCopy() changed artifactRootPath: got %q want %q",
			*clone.Spec.ArtifactRootPath,
			*original.Spec.ArtifactRootPath,
		)
	}

	if *clone.Spec.ArchiveRootSecret != *original.Spec.ArchiveRootSecret {
		t.Fatalf(
			"DeepCopy() changed archiveRootSecret: got %q want %q",
			*clone.Spec.ArchiveRootSecret,
			*original.Spec.ArchiveRootSecret,
		)
	}

	if *clone.Spec.ArchiveRootPath != *original.Spec.ArchiveRootPath {
		t.Fatalf(
			"DeepCopy() changed archiveRootPath: got %q want %q",
			*clone.Spec.ArchiveRootPath,
			*original.Spec.ArchiveRootPath,
		)
	}

	if *clone.Spec.TraceArchivalRetention != *original.Spec.TraceArchivalRetention {
		t.Fatalf(
			"DeepCopy() changed traceArchivalRetention: got %q want %q",
			*clone.Spec.TraceArchivalRetention,
			*original.Spec.TraceArchivalRetention,
		)
	}
}
