"""
Banco de preguntas genéricas que el asistente usa para ir conociendo al usuario
poco a poco durante las conversaciones.
"""

BANCO_DE_PREGUNTAS = [
    "¿Cómo te llamas y cómo prefieres que te llame?",
    "¿A qué te dedicas actualmente?",
    "¿Qué haces en tu tiempo libre?",
    "¿Tienes alguna meta importante en la que estés trabajando ahora?",
    "¿Cuál es tu comida favorita?",
    "¿Tienes mascotas? ¿Cómo se llaman?",
    "¿Qué tipo de música te gusta escuchar?",
    "¿Prefieres las mañanas o las noches para trabajar/estudiar?",
    "¿Hay algo que te esté preocupando últimamente?",
    "¿Cuál es tu lugar favorito en el mundo, o al que te gustaría ir?",
    "¿Qué tipo de películas o series te gustan?",
    "¿Tienes hermanos o hermanas? ¿Cómo es tu relación con ellos?",
    "¿Cuál es una habilidad que te gustaría aprender?",
    "¿Cómo describirías tu personalidad en pocas palabras?",
    "¿Qué es lo que más valoras en las personas que te rodean?",
    "¿Tienes algún hábito o rutina diaria importante para ti?",
    "¿Cuál ha sido un logro del que te sientes orgulloso?",
    "¿Qué te gustaría que yo, como tu asistente, te ayude a hacer más seguido?",
]


def obtener_pregunta_sin_hacer(pregunta_ya_hecha_fn):
    """Devuelve la primera pregunta del banco que no se le haya hecho al usuario."""
    for pregunta in BANCO_DE_PREGUNTAS:
        if not pregunta_ya_hecha_fn(pregunta):
            return pregunta
    return None  # ya se hicieron todas
