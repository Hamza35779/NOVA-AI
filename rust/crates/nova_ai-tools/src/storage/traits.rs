//! MemoryBackend trait for all storage backends.

use nova_ai_core::{NOVA AIError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, NOVA AIError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, NOVA AIError>;
    fn delete(&self, doc_id: &str) -> Result<bool, NOVA AIError>;
    fn clear(&self) -> Result<(), NOVA AIError>;
    fn count(&self) -> Result<usize, NOVA AIError>;
}
