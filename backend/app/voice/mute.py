"""Mute the caller's input while the agent speaks (ticket 0010).

Replaces Pipecat's ``STTMuteFilter(strategies={ALWAYS})``, deprecated since 0.0.99 in favour of
``LLMUserAggregator(user_mute_strategies=...)``. That replacement lives inside Pipecat's LLM context
aggregator, which this app's pipeline doesn't use — the intent-router engine (``EngineProcessor``)
owns each turn. So this is the same behavior on stable frame APIs: track the bot-speaking markers
and drop user audio / VAD / transcription frames between them, before STT, so the agent never
transcribes its own voice. All other frames pass through untouched.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# The frames STTMuteFilter suppressed while muted — the caller's side of the conversation.
_USER_FRAMES = (
    InterruptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)


class BotSpeakingMute(FrameProcessor):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif self._bot_speaking and isinstance(frame, _USER_FRAMES):
            return  # drop: the agent is talking
        await self.push_frame(frame, direction)
