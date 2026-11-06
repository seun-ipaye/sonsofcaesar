from types import SimpleNamespace as NS

import anthropic

from app.agent import HANDOFF, MAX_STEPS, run_agent


def text(value):
    return NS(type='text', text=value)


def call(name='get_event_info', args=None, id='t1'):
    return NS(type='tool_use', name=name, input=args or {}, id=id)


def response(*content, stop='end_turn'):
    return NS(content=list(content), stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


class FakeClient:
    """Plays back scripted responses and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **request):
        self.requests.append({**request, 'messages': list(request['messages'])})
        return self.responses.pop(0)


HELLO = [{'role': 'user', 'content': 'hi'}]


def test_plain_answer(db):
    result = run_agent(db, HELLO, FakeClient(response(text('Hello!'))))
    assert (result.reply, result.outcome, result.tools_used) == ('Hello!', 'answered', [])


def test_tool_result_goes_back_to_the_model(db):
    client = FakeClient(response(call(), stop='tool_use'), response(text('Nothing on.')))
    result = run_agent(db, HELLO, client)

    assert result.reply == 'Nothing on.' and result.tools_used == ['get_event_info']
    assert (result.input_tokens, result.output_tokens) == (20, 10)
    assistant, user = client.requests[1]['messages'][-2:]
    assert assistant['content'][0].id == 't1'  # the model's turn is kept as it was
    assert user['content'] == [{'type': 'tool_result', 'tool_use_id': 't1', 'content': '{"events": []}'}]


def test_parallel_calls_share_one_message_and_errors_are_flagged(db):
    client = FakeClient(
        response(call(id='a'), call('get_order_status', {'order_id': 'nope'}, id='b'), stop='tool_use'),
        response(text('Done.')),
    )
    run_agent(db, HELLO, client)
    results = client.requests[1]['messages'][-1]['content']
    assert [r['tool_use_id'] for r in results] == ['a', 'b']
    assert 'is_error' not in results[0] and results[1]['is_error'] is True


def test_runaway_loop_stops_and_hands_off(db):
    client = FakeClient(*[response(call(), stop='tool_use') for _ in range(MAX_STEPS + 2)])
    result = run_agent(db, HELLO, client)
    assert (result.reply, result.outcome) == (HANDOFF, 'out_of_steps')
    assert len(client.requests) == MAX_STEPS


def test_refusal_and_cutoff_hand_off(db):
    refused = run_agent(db, HELLO, FakeClient(response(stop='refusal')))
    assert (refused.reply, refused.outcome) == (HANDOFF, 'refused')
    cut = run_agent(db, HELLO, FakeClient(response(text('half a sen'), stop='max_tokens')))
    assert (cut.reply, cut.outcome) == (HANDOFF, 'cut_off')


def test_empty_answer_hands_off(db):
    assert run_agent(db, HELLO, FakeClient(response())).reply == HANDOFF


def test_api_failure_hands_off_without_raising(db, caplog):
    class Down(FakeClient):
        def create(self, **request):
            raise anthropic.APIConnectionError(request=NS(url='x', method='POST'), message='secret message text')

    result = run_agent(db, HELLO, Down())
    assert (result.reply, result.outcome) == (HANDOFF, 'error')
    assert 'secret message text' not in caplog.text
