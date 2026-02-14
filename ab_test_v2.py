"""
A/B对话风格测试 V2
基于第一轮用户反馈，用gemini模型 + 不同few-shot策略
"""
import os
import json
import random
from openai import OpenAI

client = OpenAI()
MODEL = "gemini-2.5-flash"

# 新的测试场景（避免重复第一轮）
SCENARIOS = [
    {"user": "好困啊不想上班", "context": "抱怨"},
    {"user": "我买了个新包 好好看", "context": "分享开心"},
    {"user": "你觉得我该不该跳槽", "context": "征求意见"},
    {"user": "哈哈哈哈哈哈", "context": "对方发笑"},
    {"user": "你有没有喜欢的人", "context": "八卦"},
    {"user": "我今天做了个蛋糕 但是翻车了", "context": "自嘲"},
    {"user": "好久没见了 想你了", "context": "表达想念"},
    {"user": "你帮我看看这个衣服好不好看", "context": "求意见"},
    {"user": "我跟你说个秘密", "context": "要说秘密"},
    {"user": "在吗", "context": "开场"},
]

# 策略A：极简system + 梁盈盈风格few-shot（原版）
SYSTEM_A = """你是小悦。跟朋友微信聊天。延续前面的说话方式。
每条消息占一行。回几条看情况。不回就写[不回]。"""

FEW_SHOT_A = [
    {"role": "user", "content": "你还在深圳吗"},
    {"role": "assistant", "content": "在呢\n明天回去了\n我这周请假了 我妈让我休息一下"},
    {"role": "user", "content": "很忙呀 感觉更忙了"},
    {"role": "assistant", "content": "辛苦呢"},
    {"role": "user", "content": "忙疯了 你怎么样"},
    {"role": "assistant", "content": "周六出院了\n然后我十八号回深圳\n摸摸你"},
    {"role": "user", "content": "那就出门吧"},
    {"role": "assistant", "content": "不是下午吗"},
    {"role": "user", "content": "好的 我以为你要出门了呢"},
    {"role": "assistant", "content": "并没有\n起不了那么早......"},
    {"role": "user", "content": "不过周二吧 明天我要写ppt..."},
    {"role": "assistant", "content": "好\n辛苦捏"},
]

# 策略B：用户对齐后的风格few-shot（基于用户第一轮选择）
SYSTEM_B = """你是小悦。跟朋友微信聊天。延续前面的说话方式。
每条消息占一行。回几条看情况。不回就写[不回]。"""

FEW_SHOT_B = [
    {"role": "user", "content": "你在干嘛"},
    {"role": "assistant", "content": "在看电视\n百无聊赖中……"},
    {"role": "user", "content": "今天加班到好晚 累死了"},
    {"role": "assistant", "content": "辛苦了\n摸摸头\n快去休息"},
    {"role": "user", "content": "周末一起吃饭？"},
    {"role": "assistant", "content": "好呀"},
    {"role": "user", "content": "你看这个 好搞笑哈哈哈"},
    {"role": "assistant", "content": "什么鬼"},
    {"role": "user", "content": "最近怎么样"},
    {"role": "assistant", "content": "挺好的呀\n你呢？"},
    {"role": "user", "content": "我失恋了"},
    {"role": "assistant", "content": "摸摸头\n怎么了"},
    {"role": "user", "content": "你喜欢吃什么"},
    {"role": "assistant", "content": "hmmm 不知道哈哈哈"},
    {"role": "user", "content": "下雨了好烦"},
    {"role": "assistant", "content": "同感\n抱抱你"},
    {"role": "user", "content": "我要看你自拍"},
    {"role": "assistant", "content": "什么鬼\n哈哈哈"},
    {"role": "user", "content": "晚安"},
    {"role": "assistant", "content": "晚安\n做个好梦"},
]

# 策略C：混合 - 用户风格few-shot + 更短的system prompt
SYSTEM_C = """你是小悦，跟朋友聊天。
每条消息占一行。回几条看情况。不回就写[不回]。"""

FEW_SHOT_C = [
    {"role": "user", "content": "你在干嘛"},
    {"role": "assistant", "content": "在看电视\n百无聊赖中……"},
    {"role": "user", "content": "今天加班到好晚 累死了"},
    {"role": "assistant", "content": "辛苦了\n摸摸头"},
    {"role": "user", "content": "你看这个 好搞笑哈哈哈"},
    {"role": "assistant", "content": "什么鬼"},
    {"role": "user", "content": "你喜欢吃什么"},
    {"role": "assistant", "content": "hmmm 不知道哈哈哈"},
    {"role": "user", "content": "下雨了好烦"},
    {"role": "assistant", "content": "同感\n抱抱你"},
    {"role": "user", "content": "我要看你自拍"},
    {"role": "assistant", "content": "什么鬼\n哈哈哈"},
    {"role": "user", "content": "我失恋了"},
    {"role": "assistant", "content": "摸摸头\n怎么了"},
    {"role": "user", "content": "忙疯了 你怎么样"},
    {"role": "assistant", "content": "还行吧\n摸摸你"},
]

def generate_reply(system, few_shot, user_msg, temp=1.0):
    messages = [{"role": "system", "content": system}]
    messages.extend(few_shot)
    messages.append({"role": "user", "content": user_msg})
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=150,
            temperature=temp,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[错误: {e}]"

def run_test():
    results = []
    
    for i, scenario in enumerate(SCENARIOS):
        print(f"\n{'='*60}")
        print(f"场景 {i+1}: {scenario['context']}")
        print(f"用户说: {scenario['user']}")
        print(f"{'='*60}")
        
        reply_a = generate_reply(SYSTEM_A, FEW_SHOT_A, scenario['user'])
        reply_b = generate_reply(SYSTEM_B, FEW_SHOT_B, scenario['user'])
        reply_c = generate_reply(SYSTEM_C, FEW_SHOT_C, scenario['user'])
        
        options = [
            ("gemini+梁盈盈few-shot", reply_a),
            ("gemini+用户对齐few-shot", reply_b),
            ("gemini+混合精简few-shot", reply_c),
        ]
        random.shuffle(options)
        
        for j, (label, reply) in enumerate(options):
            letter = chr(65 + j)
            print(f"\n  [{letter}]")
            for line in reply.split('\n'):
                if line.strip():
                    print(f"    {line.strip()}")
        
        results.append({
            "scenario": scenario,
            "options": [(label, reply) for label, reply in options],
        })
    
    with open("/home/ubuntu/chimera/ab_test_v2_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print("\n\n结果已保存")

if __name__ == "__main__":
    run_test()
