// StudyMate Website Interactive Scripts

document.addEventListener('DOMContentLoaded', function() {
    
    // 平滑滚动导航
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // 轻提示组件
    let toastTimer = null;
    function showToast(message) {
        let toast = document.getElementById('site-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'site-toast';
            toast.className = 'toast';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        // 强制重排，保证连续点击也能重新播放动画
        void toast.offsetWidth;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('show'), 3600);
    }

    // 体验入口按钮：内测提示 / 跳转功能演示
    document.querySelectorAll('[data-toast]').forEach(btn => {
        btn.addEventListener('click', () => showToast(btn.dataset.toast));
    });
    document.querySelectorAll('[data-scroll]').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = document.querySelector(btn.dataset.scroll);
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    // 页面滚动动画效果
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);

    // 为所有卡片元素添加滚动动画
    document.querySelectorAll('.problem-card, .feature-demo, .experience-card').forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(30px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });

    // 进度条加载动画
    setTimeout(() => {
        const progressFill = document.querySelector('.progress-fill');
        if (progressFill) {
            progressFill.style.width = '45%';
        }
    }, 500);

    // 日历日期交互效果
    const calendarDays = document.querySelectorAll('.day');
    calendarDays.forEach(day => {
        day.addEventListener('mouseenter', function() {
            this.style.transform = 'scale(1.2)';
        });
        day.addEventListener('mouseleave', function() {
            this.style.transform = 'scale(1)';
        });
    });

    // 表单提交处理
    const signupForm = document.getElementById('signup-form');
    if (signupForm) {
        signupForm.addEventListener('submit', function(e) {
            e.preventDefault();

            // 获取表单数据
            const name = this.querySelector('input[type="text"]').value.trim();
            const email = this.querySelector('input[type="email"]').value.trim();
            const statusSelect = this.querySelector('select');
            const statusLabels = {
                undergraduate: '在校本科生',
                postgrad: '考研备考',
                other: '其他'
            };
            const status = statusLabels[statusSelect.value] || statusSelect.value;

            // 显示提交成功提示
            showToast(`已在本页填写：${name}（${status}），邮箱 ${email}。这是演示表单，站点未接入后端，信息不会被提交或保存。`);

            // 重置表单
            this.reset();
        });
    }

    // 笔记摘要切换动画效果
    const noteOriginals = document.querySelectorAll('.note-original p');
    noteOriginals.forEach(note => {
        note.addEventListener('mouseover', function() {
            this.style.background = '#fff3cd';
            this.style.transition = 'background 0.3s';
        });
        note.addEventListener('mouseout', function() {
            this.style.background = 'transparent';
        });
    });

    // 错题回顾卡片点击展开详细解析
    const errorCards = document.querySelectorAll('.error-card');
    errorCards.forEach(card => {
        card.addEventListener('click', function() {
            this.style.boxShadow = '0 8px 25px rgba(91, 155, 213, 0.3)';
            setTimeout(() => {
                this.style.boxShadow = '';
            }, 500);
        });
    });

    // 导航栏滚动时阴影效果
    const navbar = document.querySelector('.navbar');
    window.addEventListener('scroll', function() {
        if (window.scrollY > 50) {
            navbar.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.15)';
        } else {
            navbar.style.boxShadow = '0 2px 10px rgba(0, 0, 0, 0.1)';
        }
    });

    // CTA 按钮悬停效果
    const ctaButton = document.querySelector('.cta-button');
    if (ctaButton) {
        ctaButton.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-3px) scale(1.05)';
        });
        ctaButton.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
        });
    }

    // 动态更新当前年份
    const footer = document.querySelector('.footer p');
    if (footer) {
        const year = new Date().getFullYear();
        footer.textContent = `© ${year} StudyMate. All rights reserved.`;
    }

    // 鼠标跟随效果（微妙的视觉反馈）
    document.addEventListener('mousemove', function(e) {
        const elements = document.querySelectorAll('.experience-btn, .submit-btn, .cta-button');
        elements.forEach(el => {
            const rect = el.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            if (x >= 0 && x <= rect.width && y >= 0 && y <= rect.height) {
                el.style.transform = 'translateY(-2px)';
            } else {
                el.style.transform = 'translateY(0)';
            }
        });
    });

    console.log('StudyMate website loaded successfully! 🎓');
});
