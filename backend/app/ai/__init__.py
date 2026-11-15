"""Earth Scope AI assistant: Gemini provider, system instruction, limits and errors.

Nothing in this package stores conversations. The chat API is stateless: the browser
sends the (bounded) active conversation with each request and the server forgets it
once the reply has been returned.
"""
