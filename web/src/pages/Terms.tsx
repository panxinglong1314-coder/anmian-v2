import LegalLayout, { type LegalDoc } from "../components/LegalLayout";

const CONTACT_EMAIL = "panxinglong-1@126.com";

const doc: Record<"en" | "zh", LegalDoc> = {
  en: {
    title: "Terms of Service",
    updated: "Last updated: May 16, 2026",
    intro:
      "Welcome to ZhiMian (“ZhiMian”, “we”, or “the Service”). Please read these Terms of Service (“Terms”) carefully before using ZhiMian and related services. By accessing or using ZhiMian, you confirm that you have read, understood, and agree to be bound by these Terms.",
    sections: [
      {
        heading: "1. The Service",
        blocks: [
          { type: "p", text: "ZhiMian is an AI bedtime companion. It primarily provides:" },
          {
            type: "ul",
            items: [
              "AI conversation companionship (pre-sleep emotional release and talking through anxiety)",
              "Sleep habit logging and analysis",
              "Cognitive Behavioral Therapy for Insomnia (CBT-I) guidance",
              "Relaxing audio such as white noise",
              "Sleep data summaries"
            ]
          },
          {
            type: "p",
            text: "We reserve the right to modify, suspend, or discontinue any part or all of the Service at any time, and will give reasonable notice where possible."
          }
        ]
      },
      {
        heading: "2. Accounts and eligibility",
        blocks: [
          { type: "p", text: "By signing in to ZhiMian with your email or a Google account, you confirm that:" },
          {
            type: "ul",
            items: [
              "You are a natural person with legal capacity, or have been duly authorized to use the account.",
              "Your use of ZhiMian complies with applicable laws and the policies of any platform you access it through.",
              "You will not use ZhiMian to engage in any unlawful activity."
            ]
          }
        ]
      },
      {
        heading: "3. Acceptable use",
        blocks: [
          {
            type: "p",
            text: "You agree not to create, copy, publish, or distribute content that is unlawful, infringing, deceptive, harmful, or that violates the rights of others. If we discover or receive reports that you have violated these standards, we may remove the relevant content, suspend, or terminate the Service without prior notice, and reserve the right to pursue remedies under applicable law."
          }
        ]
      },
      {
        heading: "4. Intellectual property",
        blocks: [
          {
            type: "p",
            text: "All content in the Service (including but not limited to text, images, audio, AI conversation logic, interface design, and code) is owned by ZhiMian and/or its licensors. You may not copy, modify, distribute, decompile, or reverse-engineer the Service’s content without our written permission."
          },
          {
            type: "p",
            text: "You retain ownership of the content you upload or submit (“User Content”), but you grant ZhiMian a worldwide, royalty-free, non-exclusive license to use your User Content as necessary to provide the Service."
          }
        ]
      },
      {
        heading: "5. Disclaimers",
        blocks: [
          {
            type: "ul",
            items: [
              "AI companionship: ZhiMian’s AI conversation features are intended to provide emotional support and sleep guidance and do not constitute professional medical diagnosis or treatment. If you are experiencing severe insomnia, anxiety, depression, or other mental-health concerns, please seek professional medical help. If you are in crisis in the US, call or text 988. ZhiMian is not liable for any delay in seeking care due to reliance on the Service.",
              "Accuracy: we strive for accuracy but are not liable for consequences arising from errors, delayed updates, or misunderstanding.",
              "Interruptions: we are not liable for service interruptions caused by force majeure (e.g., network failures, server maintenance), but will give notice where possible and restore service promptly.",
              "Third parties: the Service may link to third-party sites or services that are outside our control; we are not responsible for third-party content."
            ]
          }
        ]
      },
      {
        heading: "6. Changes and termination",
        blocks: [
          {
            type: "p",
            text: "We may modify these Terms at any time, with or without notice. Modified Terms take effect upon posting. Your continued use after the changes take effect means you accept them."
          },
          { type: "p", text: "We may suspend or terminate your account if:" },
          {
            type: "ul",
            items: [
              "You violate any of these Terms;",
              "Your use of the Service harms the legitimate rights of ZhiMian or third parties;",
              "Required by law or a lawful request from authorities."
            ]
          }
        ]
      },
      {
        heading: "7. Account deletion",
        blocks: [
          {
            type: "p",
            text: "You may delete your ZhiMian account at any time from within the app. After deletion, your personal information will be removed in accordance with our Privacy Policy. Deletion is irreversible, and related historical data (including sleep records and conversation summaries) will be cleared."
          }
        ]
      },
      {
        heading: "8. Contact us",
        blocks: [
          { type: "p", text: `Email: ${CONTACT_EMAIL}` },
          { type: "p", text: "Website: https://sleepai.chat" },
          { type: "p", text: "We aim to respond within 15 business days." }
        ]
      }
    ]
  },
  zh: {
    title: "用户协议",
    updated: "最后更新：2026 年 5 月 16 日",
    intro:
      "欢迎使用知眠（“知眠”、“我们”或“本服务”）。在您开始使用知眠及相关服务之前，请仔细阅读本用户协议（“本协议”）。您访问或使用知眠服务，即表示您已阅读、理解并同意接受本协议的约束。",
    sections: [
      {
        heading: "一、服务说明",
        blocks: [
          { type: "p", text: "知眠是一款基于人工智能的睡前陪伴应用，主要提供以下服务：" },
          {
            type: "ul",
            items: [
              "AI 语音对话陪伴（睡前情绪释放、焦虑倾诉）",
              "睡眠习惯记录与分析",
              "认知行为疗法（CBT-I）辅助引导",
              "白噪音等助眠音频",
              "睡眠数据报告"
            ]
          },
          {
            type: "p",
            text: "知眠保留随时修改、暂停或终止部分或全部服务的权利，并会尽可能提前通知用户。"
          }
        ]
      },
      {
        heading: "二、账号注册与使用",
        blocks: [
          { type: "p", text: "您通过邮箱或 Google 账号登录知眠，即表示您确认：" },
          {
            type: "ul",
            items: [
              "您是具有民事行为能力的自然人，或已获得合法授权使用相关账号。",
              "您使用知眠服务的行为符合所适用的法律法规与平台规范。",
              "您承诺不会利用知眠服务从事任何违法活动。"
            ]
          }
        ]
      },
      {
        heading: "三、内容规范",
        blocks: [
          {
            type: "p",
            text: "您在使用知眠时，应遵守内容规范，承诺不制作、复制、发布、传播任何违法、侵权、欺骗性、有害或侵犯他人合法权益的内容。如知眠发现或收到他人举报您有违反规范的行为，知眠有权不经通知地对相关内容进行删除、暂停或终止服务，并保留依法追究相关责任的权利。"
          }
        ]
      },
      {
        heading: "四、知识产权",
        blocks: [
          {
            type: "p",
            text: "知眠服务中的所有内容（包括但不限于文字、图片、音频、AI 对话逻辑、界面设计、代码等）的知识产权归知眠及/或其权利人所有。未经知眠书面许可，您不得对知眠服务的内容进行复制、修改、分发、反编译或反向工程。"
          },
          {
            type: "p",
            text: "您在使用知眠过程中自行上传、发布的内容（“用户内容”），您保留对其所有权，但您授予知眠一项全球范围内、免许可费、非独占的许可，允许知眠在提供服务的必要范围内使用您的用户内容。"
          }
        ]
      },
      {
        heading: "五、免责声明",
        blocks: [
          {
            type: "ul",
            items: [
              "AI 陪伴服务：知眠的 AI 对话功能旨在提供情感支持和睡眠辅助，不构成专业的医学诊断或治疗。如您正在经历严重的失眠、焦虑、抑郁或其他心理健康问题，请寻求专业医疗帮助；如处于危机中，请拨打当地心理援助热线。知眠不对因您依赖 AI 服务而延误就医承担任何责任。",
              "信息准确性：知眠会尽力确保信息准确性，但不对因信息错误、更新滞后或用户误解导致的后果承担责任。",
              "服务中断：知眠不对因不可抗力（如网络故障、服务器维护等）导致的服务中断承担责任，但会尽力提前通知并尽快恢复服务。",
              "第三方服务：知眠服务中可能包含指向第三方网站或服务的链接，这些第三方内容不在知眠控制范围内，知眠不对其负责。"
            ]
          }
        ]
      },
      {
        heading: "六、服务变更与终止",
        blocks: [
          {
            type: "p",
            text: "知眠有权在发出通知（或不发出通知）的情况下，随时修改本协议的内容。修改后的协议一经公布即生效。您在修改生效后继续使用知眠服务，即表示您接受修改后的协议。"
          },
          { type: "p", text: "知眠有权在以下情况下暂停或终止您的账号：" },
          {
            type: "ul",
            items: [
              "您违反本协议的任何条款；",
              "您使用知眠服务的行为损害知眠或第三方的合法权益；",
              "法律法规要求或国家机关依法提出要求。"
            ]
          }
        ]
      },
      {
        heading: "七、账号注销",
        blocks: [
          {
            type: "p",
            text: "您可以随时在应用内注销您的知眠账号。账号注销后，您的个人信息将按知眠隐私政策的规定予以删除。请注意，账号注销后将无法恢复，相关的历史数据（包括睡眠记录、对话摘要等）将被清除。"
          }
        ]
      },
      {
        heading: "八、联系我们",
        blocks: [
          { type: "p", text: `电子邮件：${CONTACT_EMAIL}` },
          { type: "p", text: "网站：https://sleepai.chat" },
          { type: "p", text: "我们将在 15 个工作日内回复您的请求。" }
        ]
      }
    ]
  }
};

export default function Terms() {
  return <LegalLayout doc={doc} />;
}
