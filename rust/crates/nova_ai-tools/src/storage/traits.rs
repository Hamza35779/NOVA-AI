//! MemoryBackend trait for all storage backends.

use nova_ai_core::{NovaError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, NovaError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, NovaError>;
    fn delete(&self, doc_id: &str) -> Result<bool, NovaError>;
    fn clear(&self) -> Result<(), NovaError>;
    fn count(&self) -> Result<usize, NovaError>;
}
