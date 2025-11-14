// 平滑捲動、簡單互動
document.addEventListener('click', (e)=>{
  const a = e.target.closest('a[href^="#"]');
  if(!a) return;
  const el = document.querySelector(a.getAttribute('href'));
  if(el){
    e.preventDefault();
    el.scrollIntoView({behavior:'smooth'});
  }
});
