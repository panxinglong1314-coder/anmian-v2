import LegalLayout, { type LegalDoc } from "../components/LegalLayout";

const CONTACT_EMAIL = "panxinglong-1@126.com";

const doc: Record<"en" | "zh", LegalDoc> = {
  en: {
    title: "Privacy Policy",
    updated: "Last updated: May 16, 2026",
    intro:
      "ZhiMian (“we”, “ZhiMian”, or “the Service”) is committed to protecting your privacy. This policy explains what information we collect, how we use and store it, and the choices you have when you use ZhiMian on the web and related services.",
    sections: [
      {
        heading: "1. Information we collect",
        blocks: [
          { type: "p", text: "We collect the following types of information:" },
          {
            type: "ul",
            items: [
              "Account information: the email address you sign in with, or, if you use Google sign-in, your verified email and basic profile from Google. We derive an internal account identifier from your email.",
              "Sleep records: sleep times, sleep quality, worries, and notes you choose to record.",
              "Voice data: when you use voice input, audio is captured only to transcribe your speech to text. Audio is discarded immediately after transcription and is not stored long-term.",
              "Usage data: in-app actions, conversation records (text summaries only — we do not retain full conversation audio), and feature-usage frequency.",
              "Device information: device type and operating-system version, used to improve the product experience."
            ]
          }
        ]
      },
      {
        heading: "2. How we use information",
        blocks: [
          { type: "p", text: "We use the information we collect only to:" },
          {
            type: "ul",
            items: [
              "Provide, maintain, and improve ZhiMian’s core features (AI bedtime companionship, sleep logging and analysis).",
              "Respond to your support requests.",
              "Send account-related service notices, if any.",
              "Comply with applicable law."
            ]
          },
          {
            type: "p",
            text: "We do not use your personal information for commercial purposes unrelated to the Service, and we do not sell or rent your personal information."
          }
        ]
      },
      {
        heading: "3. Storage and security",
        blocks: [
          {
            type: "ul",
            items: [
              "We use encryption in transit (HTTPS) and at rest, access controls, and security auditing to protect your data.",
              "Voice audio is deleted immediately after speech-to-text completes and is not retained.",
              "After you delete your account, your sleep records and account data are deleted or anonymized within 30 days."
            ]
          }
        ]
      },
      {
        heading: "4. Sharing and third parties",
        blocks: [
          { type: "p", text: "We do not share your personal information with third parties except:" },
          {
            type: "ul",
            items: [
              "With your explicit consent.",
              "Where required by law, courts, or regulators.",
              "Where necessary to protect the safety of ZhiMian, our users, or the public."
            ]
          },
          {
            type: "p",
            text: "We use third-party AI providers to process speech-to-text and AI conversation. In this process your text content is transmitted to the provider, but it does not include information used to identify you."
          }
        ]
      },
      {
        heading: "4b. Enterprise / employer-provided accounts",
        blocks: [
          {
            type: "p",
            text: "If you signed up using an invite code from your employer (enterprise account), what your employer can and cannot see is strictly limited:"
          },
          {
            type: "ul",
            items: [
              "Your employer NEVER sees your identity tied to any specific conversation, sleep entry, worry, or crisis event.",
              "Your employer ONLY sees team-level anonymized aggregates (e.g., \"average sleep efficiency on this team\", \"count of high-risk events this month\"). Teams smaller than 5 active members are not shown.",
              "Crisis events: when you mention self-harm or suicide, ZhiMian routes you to professional resources (988 Suicide & Crisis Lifeline, etc.). Your employer is NOT notified of who triggered the event — only a team-level count.",
              "You can leave the enterprise account at any time from your Profile. Your personal conversations, sleep records, and worries remain yours; they stop contributing to your employer's aggregates the moment you leave."
            ]
          }
        ]
      },
      {
        heading: "5. Your rights",
        blocks: [
          {
            type: "ul",
            items: [
              "Access: you may contact us to learn what personal information we hold about you.",
              "Correction: you may correct inaccurate personal information.",
              "Deletion: you may delete your account and all personal information at any time from within the app.",
              "Withdraw consent: you may revoke microphone and other permissions in your browser settings; some features may be affected."
            ]
          }
        ]
      },
      {
        heading: "6. Children’s privacy",
        blocks: [
          {
            type: "p",
            text: "ZhiMian is not directed to children under 14 and we do not knowingly collect personal information from children. If you are under 14, please use ZhiMian only with the consent and guidance of a parent or guardian."
          }
        ]
      },
      {
        heading: "7. Not a medical service",
        blocks: [
          {
            type: "p",
            text: "ZhiMian provides emotional support and sleep guidance based on CBT-I principles. It does not provide medical diagnosis or treatment. If you are in crisis in the US, call or text 988 (Suicide & Crisis Lifeline)."
          }
        ]
      },
      {
        heading: "8. Changes to this policy",
        blocks: [
          {
            type: "p",
            text: "We may update this policy from time to time. The updated policy will be posted on this page with a new “Last updated” date. For material changes we will notify you in-app or on the site."
          }
        ]
      },
      {
        heading: "9. Contact us",
        blocks: [
          { type: "p", text: `Email: ${CONTACT_EMAIL}` },
          { type: "p", text: "Website: https://sleepai.chat" },
          { type: "p", text: "We aim to respond within 15 business days." }
        ]
      }
    ]
  },
  zh: {
    title: "隐私政策",
    updated: "最后更新：2026 年 5 月 16 日",
    intro:
      "知眠（“我们”、“知眠”或“本服务”）承诺保护您的个人隐私。本隐私政策说明了我们在您使用知眠 Web 应用及相关服务时，如何收集、使用、存储和保护您提供的信息。",
    sections: [
      {
        heading: "一、信息收集",
        blocks: [
          { type: "p", text: "我们收集以下类型的信息：" },
          {
            type: "ul",
            items: [
              "账号信息：您用以登录的邮箱地址；若使用 Google 登录，则为 Google 提供的已验证邮箱与基本资料。",
              "睡眠记录：您主动记录的睡眠时间、睡眠质量、梦境、焦虑事项等。",
              "语音数据：您使用语音输入时采集的音频，仅用于语音转文字。所有语音数据在处理完成后立即丢弃，不会长期存储。",
              "使用数据：应用内操作行为、会话记录（仅保留文字摘要，不保留完整对话音频）、功能使用频率。",
              "设备信息：设备型号、操作系统版本，用于优化产品体验。"
            ]
          }
        ]
      },
      {
        heading: "二、信息使用",
        blocks: [
          { type: "p", text: "我们收集的信息仅用于以下目的：" },
          {
            type: "ul",
            items: [
              "提供、维持和改进知眠的核心功能（AI 睡前陪伴、睡眠记录与分析）",
              "响应您的用户支持请求",
              "发送与您账号相关的服务通知（如有）",
              "遵守法律法规要求"
            ]
          },
          {
            type: "p",
            text: "我们不会将您的个人信息用于与提供知眠服务无关的商业目的，也不会出售、出租您的个人信息。"
          }
        ]
      },
      {
        heading: "三、信息存储与安全",
        blocks: [
          {
            type: "ul",
            items: [
              "我们采用加密传输（HTTPS）与存储、访问控制、安全审计等措施保护您的数据安全。",
              "语音音频在语音转文字完成后立即删除，不做长期保存。",
              "您的睡眠记录和账号数据，在您注销账号后将在 30 天内予以删除或匿名化处理。"
            ]
          }
        ]
      },
      {
        heading: "四、信息共享",
        blocks: [
          { type: "p", text: "除以下情形外，我们不会与任何第三方共享您的个人信息：" },
          {
            type: "ul",
            items: [
              "已获得您的明确同意。",
              "根据法律法规、司法机关或监管部门的要求必须提供。",
              "为保护知眠、用户或公众的人身财产安全所必需。"
            ]
          },
          {
            type: "p",
            text: "我们使用第三方 AI 服务处理您的语音转文字和 AI 对话请求。在此过程中，您的文字内容会被传输至 AI 服务提供商，但不会包含可用于识别您身份的信息。"
          }
        ]
      },
      {
        heading: "四(B)、企业 / 公司提供的账号",
        blocks: [
          {
            type: "p",
            text: "如果你是通过公司提供的邀请码加入(企业版账号),公司能看到和不能看到的内容严格隔离:"
          },
          {
            type: "ul",
            items: [
              "公司**永远**无法看到任何具体对话内容、睡眠条目、担忧文本、危机事件的身份信息。",
              "公司**仅**看到团队层级的匿名聚合数据(如\"本团队平均睡眠效率\"、\"本月高风险事件计数\")。少于 5 名活跃成员的小团队不展示数据。",
              "危机事件:你提到自伤/自杀时,知眠会引导你联系全国心理援助热线 (400-161-9995)、北京心理危机研究中心 (010-82951332) 等专业资源。公司**不会**被告知是谁触发的,只看到团队级数字计数。",
              "你随时可以在「我的」页面退订企业账号。退订后你的对话、睡眠记录仍归你所有,但不再算入公司聚合数据。"
            ]
          }
        ]
      },
      {
        heading: "五、用户权利",
        blocks: [
          {
            type: "ul",
            items: [
              "查阅权：您可以联系我们了解我们持有您哪些个人信息。",
              "更正权：您可以更正不准确的个人信息。",
              "删除权：您可以随时在应用内注销账号并删除全部个人信息。",
              "撤回同意：您可以在浏览器设置中撤回麦克风等权限，撤回后部分功能将受影响。"
            ]
          }
        ]
      },
      {
        heading: "六、儿童隐私",
        blocks: [
          {
            type: "p",
            text: "知眠不面向未满 14 周岁的儿童，也不故意收集儿童个人信息。如果您是未满 14 周岁的儿童，请在使用知眠前获得家长或监护人的同意和指导。"
          }
        ]
      },
      {
        heading: "七、不是医疗服务",
        blocks: [
          {
            type: "p",
            text: "知眠基于 CBT-I 理念提供情感支持和睡眠辅助，不提供医学诊断或治疗。如您正处于危机中，请拨打当地心理援助热线（中国内地可拨 400-161-9995）。"
          }
        ]
      },
      {
        heading: "八、隐私政策更新",
        blocks: [
          {
            type: "p",
            text: "我们可能会不时更新本隐私政策。更新后的隐私政策将在此页面公布，并注明新的“最后更新”日期。如有重大变更，我们将通过应用内通知或网站公告告知您。"
          }
        ]
      },
      {
        heading: "九、联系我们",
        blocks: [
          { type: "p", text: `电子邮件：${CONTACT_EMAIL}` },
          { type: "p", text: "网站：https://sleepai.chat" },
          { type: "p", text: "我们将在 15 个工作日内回复您的请求。" }
        ]
      }
    ]
  }
};

export default function Privacy() {
  return <LegalLayout doc={doc} />;
}
