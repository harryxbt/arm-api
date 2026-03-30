import json
from unittest.mock import patch, MagicMock

from app.services.clip_analyzer import analyze_transcript, format_transcript


class TestFormatTranscript:
    def test_formats_words_with_timestamps(self):
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]
        result = format_transcript(words)
        assert "[0:00]" in result
        assert "Hello" in result
        assert "world" in result

    def test_empty_words(self):
        result = format_transcript([])
        assert result == ""


class TestAnalyzeTranscript:
    @patch("app.services.clip_analyzer.OpenAI")
    def test_returns_clips(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "clips": [
                {
                    "start_time": 10.0,
                    "end_time": 55.0,
                    "virality_score": 85,
                    "hook_text": "You won't believe this",
                    "reasoning": "Strong hook"
                }
            ]
        })
        mock_client.chat.completions.create.return_value = mock_response

        words = [{"word": "test", "start": 0.0, "end": 1.0}]
        result = analyze_transcript(words, video_duration=120.0)

        assert len(result) == 1
        assert result[0]["virality_score"] == 85
        assert result[0]["start_time"] == 10.0
        assert result[0]["end_time"] == 55.0

    @patch("app.services.clip_analyzer.OpenAI")
    def test_filters_out_of_bounds_clips(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "clips": [
                {"start_time": 10.0, "end_time": 55.0, "virality_score": 85,
                 "hook_text": "Good clip", "reasoning": "ok"},
                {"start_time": 100.0, "end_time": 200.0, "virality_score": 90,
                 "hook_text": "Bad clip", "reasoning": "out of bounds"},
            ]
        })
        mock_client.chat.completions.create.return_value = mock_response

        words = [{"word": "test", "start": 0.0, "end": 1.0}]
        result = analyze_transcript(words, video_duration=60.0)

        assert len(result) == 1
        assert result[0]["hook_text"] == "Good clip"
