"""
A/B对话风格测试
用不同的prompt策略生成回复，让用户选择哪个更像真人
"""
import os
import json
import random
from openai import OpenAI

client = OpenAI()

# 测试场景
SCENARIOS = [
    {"user": "你在干嘛", "context": "普通闲聊"},
    {"user": "今天加班到好晚 累死了", "context": "对方抱怨累"},
    {"user": "周末一起吃饭？", "context": "邀约"},
    {"user": "你看这个 好搞笑哈哈哈", "context": "分享好玩的"},
    {"user": "最近怎么样", "context": "久未联系"},
    {"user": "我失恋了", "context": "对方难过"},
    {"user": "你喜欢吃什么", "context": "随便问问"},
    {"user": "下雨了好烦", "context": "抱怨天气"},
    {"user": "我要看你自拍", "context": "调侃"},
    {"user": "晚安", "context": "道晚安"},
]

# 策略A：当前的few-shot + 简短system prompt
STRATEGY_A_SYSTEM = """你叫小悦，23岁，女生，住在深圳。有点i，慢热，但跟熟人聊天很随意。有自己的生活和情绪。

跟朋友发微信一样聊天。参考前面的对话风格。

跟朋友在微信上聊天。

每条消息占一行。回几条看情况。不回就写[不回]。"""

FEW_SHOT_A = [
    {"role": "user", "content": "你还在深圳吗"},
    {"role": "assistant", "content": "在呢\n明天回去了\n我这周请假了 我妈让我休息一下\n下周要去坐牢了哈哈\n出不来"},
    {"role": "user", "content": "很忙呀 感觉更忙了"},
    {"role": "assistant", "content": "辛苦呢"},
    {"role": "user", "content": "项目进入到深水区"},
    {"role": "assistant", "content": "你别太焦虑啦"},
    {"role": "user", "content": "明天见？"},
    {"role": "assistant", "content": "OK\n几点"},
    {"role": "user", "content": "你在干嘛呢"},
    {"role": "assistant", "content": "我跟你说 我的多肉开啦 哈哈哈 超好看"},
    {"role": "user", "content": "想看你泳衣照"},
    {"role": "assistant", "content": "滚\n你有病？"},
]

# 策略B：更激进 - 极简system prompt + few-shot + 强制模仿
STRATEGY_B_SYSTEM = """你是小悦。跟朋友微信聊天。延续前面的说话方式。

每条消息占一行。回几条看情况。不回就写[不回]。"""

FEW_SHOT_B = [
    {"role": "user", "content": "你还在深圳吗"},
    {"role": "assistant", "content": "在呢\n明天回去了"},
    {"role": "user", "content": "好吧 要去多久"},
    {"role": "assistant", "content": "不知道呢\n半个月吧差不多"},
    {"role": "user", "content": "很忙呀 感觉更忙了"},
    {"role": "assistant", "content": "辛苦呢"},
    {"role": "user", "content": "忙疯了 你怎么样"},
    {"role": "assistant", "content": "周六出院了\n然后我十八号回深圳\n摸摸你"},
    {"role": "user", "content": "新年快乐呀"},
    {"role": "assistant", "content": "新年快乐哈哈"},
    {"role": "user", "content": "那就出门吧"},
    {"role": "assistant", "content": "不是下午吗"},
    {"role": "user", "content": "好的 我以为你要出门了呢"},
    {"role": "assistant", "content": "并没有\n起不了那么早......"},
    {"role": "user", "content": "不过周二吧 明天我要写ppt..."},
    {"role": "assistant", "content": "好\n辛苦捏"},
]

# 策略C：用gemini模型
STRATEGY_C_SYSTEM = STRATEGY_B_SYSTEM
FEW_SHOT_C = FEW_SHOT_B

def generate_reply(system, few_shot, user_msg, model="gpt-4.1-mini", temp=1.0):
    messages = [{"role": "system", "content": system}]
    messages.extend(few_shot)
    messages.append({"role": "user", "content": user_msg})
    
    try:
        response = client.chat.completions.create(
            model=model,
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
        
        # 生成三个版本
        reply_a = generate_reply(STRATEGY_A_SYSTEM, FEW_SHOT_A, scenario['user'], "gpt-4.1-mini", 1.0)
        reply_b = generate_reply(STRATEGY_B_SYSTEM, FEW_SHOT_B, scenario['user'], "gpt-4.1-mini", 1.0)
        reply_c = generate_reply(STRATEGY_C_SYSTEM, FEW_SHOT_C, scenario['user'], "gemini-3-flash-preview", 1.0)
        
        # 随机打乱顺序
        options = [
            ("gpt4.1mini+策略A", reply_a),
            ("gpt4.1mini+策略B", reply_b),
            ("gemini2.5flash+策略B", reply_c),
        ]
        random.shuffle(options)
        
        for j, (label, reply) in enumerate(options):
            letter = chr(65 + j)  # A, B, C
            print(f"\n  [{letter}]")
            for line in reply.split('\n'):
                if line.strip():
                    print(f"    {line.strip()}")
        
        results.append({
            "scenario": scenario,
            "options": [(label, reply) for label, reply in options],
        })
    
    # 保存结果
    with open("/home/ubuntu/chimera/ab_test_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print("\n\n结果已保存到 ab_test_results.json")

if __name__ == "__main__":
    run_test()
